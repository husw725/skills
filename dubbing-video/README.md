# dubbing-video

本项目在 Mac 上编辑代码，通过 GitHub 同步，在 Windows 原生环境执行。

## 连接试运行

- 仓库：`https://github.com/husw725/skills.git`
- 分支：`codex/dubbing-video-win-smoke`
- Windows 独立检出目录：`E:\workspace\dubbing-video-smoke`
- 项目目录：检出目录下的 `dubbing-video`
- 连接：Mac 执行 `ssh win`

Windows 运行命令：

```powershell
Set-Location E:\workspace\dubbing-video-smoke
git pull --ff-only
Set-Location dubbing-video
python smoke_test.py
```

脚本只允许在 Windows 执行，打印主机、Python 和 Git 提交信息，并写入
`output/smoke-result.json`，随后读取核验。无第三方依赖；产物不提交。

当前仅验证代码传递与远程运行，配音业务等待后续需求。
