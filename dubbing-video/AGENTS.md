# dubbing-video 工作规则

- 开工读 CODEX_HANDOFF.md 和 ../codex-migration/WORKSPACE_RULES.md（实际共享文件在 /Users/husw/demo/codex-migration/WORKSPACE_RULES.md）。
- 用户要求：后续所有剧/集的翻译必须结合剧本。先获取剧本并核对与成片、字幕的版本，再梳理人名、术语、关系、场景和情绪，逐句优化巴葡译文。
- 成片和字幕原对白、时间码优先；剧本不能引入缺失台词。剧本说话人/情绪证据与原声听审标记分开，未知配音者保留 unknown。
- 使用 reviewed screenplay-context JSON，保留剧本版本、SHA256、对应字幕证据及上下文指纹。修改后重新审核，不能复用另一版本断点。
- 默认不使用 subtitle-only；无剧本时继续查找并向用户说明缺项，只有用户明确同意才按字幕单独翻译。
- Mac写代码，经GitHub push后Windows pull并执行业务；真实素材/字幕/译稿仅放忽略的input/output，密钥不进Git。
