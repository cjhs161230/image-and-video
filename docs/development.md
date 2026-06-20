# 开发说明

安装依赖后使用以下命令验证：

```powershell
uv --cache-dir .uv-cache run pytest -q --basetemp=data\test-tmp
uv --cache-dir .uv-cache run ruff check .
uv --cache-dir .uv-cache run pyright
npm run lint
npm run format:check
npm run test:e2e
python scripts\security\scan_secrets.py .
```

行为变更必须先写失败测试，再实现最小代码，再运行验证。

启动：

```powershell
start.bat
```

默认访问地址为 `http://127.0.0.1:17860`。如端口被占用，在 `.env` 中设置 `IMAGE_VIDEO_PORT` 为其他未占用端口；`IMAGE_VIDEO_HOST` 应保持 `127.0.0.1`。

Matsca native 模式返回的图片 URL 可能指向官方图片资源。若下载阶段出现 `403 Forbidden`、连接超时或无法访问资源，在普通设置中配置 `native_download_proxy`，例如：

```json
{
  "native_download_proxy": "http://127.0.0.1:7890"
}
```

该代理只用于 native 结果图片下载阶段，不应写入 `.env`，也不要把代理日志或上游完整 URL 提交到 Git。

停止：

```powershell
stop.bat
```
