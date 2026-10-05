import asyncio
import json
import os
import subprocess
from pathlib import Path
from aiohttp import web, ClientSession, ClientTimeout

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_API_BASE", "http://127.0.0.1:11434")

routes = web.RouteTableDef()


def get_git_info():
    branch = "main"
    status_summary = []
    try:
        res = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode == 0 and res.stdout.strip():
            branch = res.stdout.strip()
    except Exception:
        pass

    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if line.strip():
                    status_summary.append(line.strip())
    except Exception:
        pass

    return branch, status_summary


def scan_files(base_path: Path):
    items = []
    ignore_names = {".git", "__pycache__", ".DS_Store", "node_modules", ".venv", "venv"}
    
    for root, dirs, files in os.walk(base_path):
        dirs[:] = [d for d in dirs if d not in ignore_names]
        rel_root = Path(root).relative_to(base_path)
        
        for file in sorted(files):
            if file in ignore_names:
                continue
            rel_path = (rel_root / file) if str(rel_root) != "." else Path(file)
            full_path = Path(root) / file
            try:
                size = full_path.stat().st_size
            except OSError:
                size = 0
            items.append({
                "path": str(rel_path),
                "name": file,
                "size": size,
                "ext": full_path.suffix.lstrip(".").lower() or "txt",
            })
    return sorted(items, key=lambda x: x["path"])


@routes.get("/")
async def handle_index(request):
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return web.FileResponse(index_file)
    return web.Response(text="Ajan Studio UI bulunamadı.", status=404)


@routes.get("/api/workspace")
async def handle_workspace(request):
    branch, status_list = get_git_info()
    files = scan_files(WORKSPACE_DIR)
    
    # Map status
    status_map = {}
    for st in status_list:
        code = st[:2].strip()
        f_name = st[3:].strip()
        status_map[f_name] = code

    for f in files:
        f["git_status"] = status_map.get(f["path"], "")

    return web.json_response({
        "workspace": str(WORKSPACE_DIR),
        "name": WORKSPACE_DIR.name,
        "branch": branch,
        "files": files,
        "dirty": len(status_list) > 0,
        "uncommitted_count": len(status_list),
    })


@routes.get("/api/file")
async def handle_get_file(request):
    rel_path = request.query.get("path")
    if not rel_path:
        return web.json_response({"error": "Path required"}, status=400)
    
    file_path = (WORKSPACE_DIR / rel_path).resolve()
    if not str(file_path).startswith(str(WORKSPACE_DIR)):
        return web.json_response({"error": "Unauthorized access"}, status=403)
    
    if not file_path.is_file():
        return web.json_response({"error": "File not found"}, status=404)

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return web.json_response({
            "path": rel_path,
            "content": content,
            "lines": len(content.splitlines()),
            "size": file_path.stat().st_size,
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@routes.post("/api/file")
async def handle_save_file(request):
    try:
        data = await request.json()
        rel_path = data.get("path")
        content = data.get("content", "")
        if not rel_path:
            return web.json_response({"error": "Path required"}, status=400)
        
        file_path = (WORKSPACE_DIR / rel_path).resolve()
        if not str(file_path).startswith(str(WORKSPACE_DIR)):
            return web.json_response({"error": "Unauthorized access"}, status=403)
        
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return web.json_response({"success": True, "path": rel_path, "size": len(content)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@routes.get("/api/git/diff")
async def handle_git_diff(request):
    rel_path = request.query.get("path")
    cmd = ["git", "diff", "HEAD"]
    if rel_path:
        cmd.append(rel_path)
    try:
        res = subprocess.run(
            cmd,
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return web.json_response({"diff": res.stdout, "error": res.stderr})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@routes.post("/api/git/commit")
async def handle_git_commit(request):
    try:
        data = await request.json()
        message = data.get("message", "Update from Ajan Studio").strip()
        if not message:
            message = "Update from Ajan Studio"

        add_res = subprocess.run(["git", "add", "."], cwd=WORKSPACE_DIR, capture_output=True, text=True)
        if add_res.returncode != 0:
            return web.json_response({"error": add_res.stderr}, status=400)

        commit_res = subprocess.run(["git", "commit", "-m", message], cwd=WORKSPACE_DIR, capture_output=True, text=True)
        return web.json_response({
            "success": commit_res.returncode == 0,
            "output": commit_res.stdout or commit_res.stderr
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@routes.post("/api/terminal")
async def handle_terminal(request):
    try:
        data = await request.json()
        command = data.get("command", "").strip()
        if not command:
            return web.json_response({"error": "Command required"}, status=400)

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=WORKSPACE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            return web.json_response({
                "command": command,
                "exit_code": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            })
        except asyncio.TimeoutError:
            proc.kill()
            return web.json_response({"error": "Command timed out after 30s"}, status=408)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@routes.get("/api/models")
async def handle_models(request):
    try:
        async with ClientSession(timeout=ClientTimeout(total=2.0)) as session:
            async with session.get(f"{OLLAMA_BASE_URL}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    return web.json_response({"connected": True, "models": models})
    except Exception:
        pass
    return web.json_response({
        "connected": False,
        "models": ["qwen2.5-coder:7b", "qwen2.5-coder:3b", "mistral:latest"],
        "error": "Ollama bağlantısı kurulamadı. 'ollama serve' çalıştığından emin olun."
    })


@routes.post("/api/chat")
async def handle_chat_stream(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    model = data.get("model", "qwen2.5-coder:7b")
    messages = data.get("messages", [])
    active_file = data.get("active_file")
    active_content = data.get("active_content", "")
    mode = data.get("mode", "agent")  # 'agent', 'architect', 'chat'

    # Build system prompt tailored to Claude Code / Antigravity standard
    files = scan_files(WORKSPACE_DIR)
    file_list_str = "\n".join([f"- {f['path']} ({f['size']} bytes)" for f in files[:40]])

    system_instruction = f"""Sen Antigravity ve Claude Code standartlarında çalışan elit bir Yerel Yazılım Mühendisi Ajanısın (AI Coding Agent).
Çalışma dizini: {WORKSPACE_DIR.name}
Mevcut Proje Dosyaları:
{file_list_str}
"""

    if active_file and active_content:
        system_instruction += f"""
Kullanıcının şu anda açık tuttuğu ve üzerinde çalıştığı aktif dosya: `{active_file}`
İçeriği:
```{Path(active_file).suffix.lstrip('.') or 'text'}
{active_content[:4000]}
```
"""

    if mode == "architect":
        system_instruction += """
GÖREVİN: "MİMARİ MOD" (Architect Mode).
- Kodları doğrudan aceleyle değiştirmek yerine önce derinlemesine düşün, planla ve adım adım tasarım mimarisini kur.
- Düşünce sürecini net açıkla, riskleri değerlendir ve kullanıcıya net bir yol haritası sun.
"""
    elif mode == "agent":
        system_instruction += """
GÖREVİN: "KOD AJANI MODU" (Code Agent Mode).
- Kullanıcının isteğini doğrudan çalışan, temiz, endüstri standardı kodlarla çöz.
- Bir dosyayı değiştireceksen veya yeni dosya oluşturacaksan, yanıtında şu formatta tam kod veya diff bloğu sağla:
```file:dosya_yolu.py
# kod içeriği buraya
```
- Ajan Studio bu blokları doğrudan algılayıp kullanıcıya tek tıkla "Kodu Projeye Uygula" (Apply Changes) butonu sunar.
"""
    else:
        system_instruction += """
GÖREVİN: "SOHBET & İZAHAT MODU".
- Kodu incele, açıkla, soruları yanıtla.
"""

    ollama_messages = [{"role": "system", "content": system_instruction}]
    for m in messages:
        ollama_messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})

    response = web.StreamResponse(
        status=200,
        reason='OK',
        headers={
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
        }
    )
    await response.prepare(request)

    async def send_sse(event_type, payload):
        msg = f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        await response.write(msg.encode("utf-8"))

    try:
        async with ClientSession(timeout=ClientTimeout(total=300.0)) as session:
            async with session.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": model,
                    "messages": ollama_messages,
                    "stream": True,
                    "options": {
                        "temperature": 0.2 if mode == "agent" else 0.7,
                        "num_predict": 4096,
                    }
                }
            ) as resp:
                if resp.status != 200:
                    err_txt = await resp.text()
                    await send_sse("error", {"message": f"Ollama Hatası ({resp.status}): {err_txt}"})
                    await send_sse("done", {})
                    return response

                in_think = False
                async for line in resp.content:
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        continue
                    try:
                        chunk = json.loads(line_str)
                        content = chunk.get("message", {}).get("content", "")
                        done = chunk.get("done", False)

                        if "<think>" in content:
                            in_think = True
                            parts = content.split("<think>")
                            if parts[0]:
                                await send_sse("content", {"text": parts[0]})
                            if len(parts) > 1 and parts[1]:
                                await send_sse("thought", {"text": parts[1]})
                            continue

                        if "</think>" in content:
                            in_think = False
                            parts = content.split("</think>")
                            if parts[0]:
                                await send_sse("thought", {"text": parts[0]})
                            if len(parts) > 1 and parts[1]:
                                await send_sse("content", {"text": parts[1]})
                            continue

                        if in_think:
                            await send_sse("thought", {"text": content})
                        else:
                            await send_sse("content", {"text": content})

                        if done:
                            break
                    except Exception:
                        continue

        await send_sse("done", {})
    except Exception as e:
        await send_sse("error", {"message": str(e)})
        await send_sse("done", {})

    return response


# Static files route
routes.static('/static', STATIC_DIR)

app = web.Application()
app.add_routes(routes)

if __name__ == "__main__":
    port = int(os.environ.get("STUDIO_PORT", 8585))
    print(f"⚡ Antigravity Local Studio başlatılıyor: http://127.0.0.1:{port}")
    web.run_app(app, host="127.0.0.1", port=port)
