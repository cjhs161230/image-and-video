# 旧数据迁移

迁移脚本：

```powershell
python scripts\migration\migrate_legacy.py <legacy_root> <legacy_database>
```

行为：

- 使用 SQLite backup API 读取旧库快照，不修改旧库。
- 按记录中的 `save_path`、`url_path` 定位媒体。
- 复制媒体到 `data/migration/media`。
- 计算大小和 SHA-256。
- 缺失媒体标记为 `missing`。
- 归档旧 `.log` 文件。
- 不导入旧 `.env`、`config.json` 或任何密钥配置。
- 生成 `data/migration/migration_report.json`。
