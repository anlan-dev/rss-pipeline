# 每日采集入口：定位 python 并执行 collect.py。
# 路径均从 $PSScriptRoot 推导，可跨机器使用。

$pipeline = $PSScriptRoot

$py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $py) { throw "未找到 python，请先安装并加入 PATH" }

Set-Location $pipeline
& $py (Join-Path $pipeline "collect.py")
