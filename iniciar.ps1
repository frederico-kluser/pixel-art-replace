# pixel-art-replace — UM comando só: instala o que falta e abre a interface.
# Uso:  .\iniciar.ps1        (a partir de qualquer pasta)
# O upload das imagens faz-se NA PÁGINA — nada de imagens por terminal.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> dependências Python (idempotente)"
python -m pip install -r requirements.txt | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Erro: pip falhou — Solução: confirme que o Python 3.10+ está no PATH"
    exit 1
}

if (-not (Test-Path "web\dist\index.html")) {
    Write-Host "==> a construir a interface (só na primeira vez)"
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Host "Erro: npm não encontrado — Solução: instale o Node.js (https://nodejs.org) e volte a correr .\iniciar.ps1"
        exit 1
    }
    Push-Location web
    npm install
    if ($LASTEXITCODE -ne 0) { Pop-Location; Write-Host "Erro: npm install falhou — Solução: rede/proxy?"; exit 1 }
    npm run build
    if ($LASTEXITCODE -ne 0) { Pop-Location; Write-Host "Erro: build da interface falhou — Solução: veja o erro acima"; exit 1 }
    Pop-Location
}

Write-Host "==> a subir o studio — o navegador abre sozinho (http://127.0.0.1:8770/)"
python -m par up --out trabalho
