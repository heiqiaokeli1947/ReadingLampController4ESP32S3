---
name: "cross-project-kb"
description: "跨项目通用知识库入口。涉及 ESP32/MicroPython 的设计、模块复用、排障，或功能硬件验证通过后，先读 d:\\develop\\ESP32\\_KB\\SKILL.md 并按规程执行。"
---

# 跨项目知识库入口

完整规程：`d:\develop\ESP32\_KB\SKILL.md`
索引：`d:\develop\ESP32\_KB\00-INDEX.md`

1. 开始设计或复用模块前，先读索引并按关键词检索。
2. 按规程区分 `hardware` / `code-only` 使用条目。
3. 功能通过硬件验证后按规程回写：

```powershell
cd d:\develop\ESP32\_KB
python tools\kb.py new --type pit --title "结论式标题" --tags a,b --verified hardware --source 项目@文件
python tools\kb.py index
python tools\kb.py lint
```
