param([string]$Python = 'python', [string]$MakeNSIS = 'makensis.exe', [switch]$SkipTests)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& $Python -m venv .build-venv
if ($LASTEXITCODE -ne 0) { throw '创建 Python 虚拟环境失败' }
$runtime = Join-Path $PSScriptRoot '.build-venv/Scripts/python.exe'
& $runtime -m pip install -r source/requirements.txt
if ($LASTEXITCODE -ne 0) { throw '安装依赖失败' }
if (-not $SkipTests) {
    & $runtime -m unittest discover -s source -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) { throw '测试失败，停止构建' }
}
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.build-cache'
$stage = Join-Path $PSScriptRoot ('.build/public-' + [guid]::NewGuid().ToString('N'))
& $runtime release_tools.py stage --root $PSScriptRoot --output $stage
if ($LASTEXITCODE -ne 0) { throw 'Release staging failed' }
$catalog = (Join-Path $stage 'catalog.json') + ';.'
& $runtime -m PyInstaller --noconfirm --clean --onefile --windowed --name CodexModelSwitch --distpath dist --workpath .build --specpath . --collect-all customtkinter --add-data $catalog (Join-Path $stage 'app.py')
if ($LASTEXITCODE -ne 0) { throw 'EXE 构建失败' }
$payload = Join-Path $PSScriptRoot 'dist/CodexModelSwitch.exe'
$guide = Join-Path $PSScriptRoot '使用说明.md'
$output = Join-Path $PSScriptRoot 'dist/CodexModelSwitch-Setup-1.6.exe'
& $MakeNSIS "/DPAYLOAD=$payload" "/DREADME_PATH=$guide" "/DOUTPUT_FILE=$output" 'installer/setup.nsi'
if ($LASTEXITCODE -ne 0) { throw '安装包构建失败，请检查 NSIS 路径' }
Write-Output "安装包已生成：$output"

& $runtime release_tools.py source --root $PSScriptRoot --output (Join-Path $PSScriptRoot 'dist/CodexModelSwitch-Source-v1.6.zip')
if ($LASTEXITCODE -ne 0) { throw 'Source packaging failed' }
