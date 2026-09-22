# NAO REMOVA O BOM DESTE ARQUIVO.
#
# O Windows PowerShell 5.1 -- o que vem no Windows -- le .ps1 como ANSI quando o
# arquivo nao comeca com BOM de UTF-8. Sem ele, um nome com acento no atalho
# acento vira "TranscriAAo de Aaudio.url" no nome do atalho, na Area de Trabalho
# do cliente. Testado: acontece.

# Instalacao na maquina do cliente. Roda UMA vez, pelo instalar.bat ao lado.
#
# Faz tres coisas e nenhuma exige que o cliente digite nada:
#   1. carrega a imagem do .tar, se ele estiver aqui na pasta;
#   2. sobe o container com o docker-compose.yml deste diretorio;
#   3. poe na Area de Trabalho o atalho que a pessoa vai usar todo dia.
#
# O atalho e um .url -- e nao um script -- de proposito: e o unico formato que
# nao tem nada que antivirus ou politica de grupo possam bloquear. Ele so abre o
# navegador no endereco. Quem cuida de o servico estar de pe e o Docker, pelo
# `restart: unless-stopped` do compose.
#
# Este .ps1 existe porque .bat e codepage do console nao lidam bem com acento:
# o atalho do plano B precisa nascer com o nome certo, e aqui o PowerShell
# grava em UTF-8 sem depender de chcp.

$ErrorActionPreference = 'Stop'
$aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$raiz = Split-Path -Parent $aqui

function Passo($texto) { Write-Host "  $texto" -ForegroundColor Cyan }
function Falha($texto) { Write-Host "  $texto" -ForegroundColor Red }

Write-Host ""
Write-Host "Instalando AudioToText" -ForegroundColor White
Write-Host ""

# --- 1. Docker respondendo? ------------------------------------------------
Passo "Procurando o Docker..."
try {
    docker version --format '{{.Server.Version}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw }
} catch {
    Falha "O Docker Desktop nao esta respondendo."
    Falha "Abra o Docker Desktop, espere a baleia ficar parada e rode este instalador de novo."
    Read-Host "`n  Enter para fechar"
    exit 1
}

# --- 2. Imagem: do .tar quando ele veio junto ------------------------------
$tar = Join-Path $aqui 'transcricao-audio.tar'
if (Test-Path $tar) {
    Passo "Carregando a aplicacao do arquivo (leva alguns minutos)..."
    docker load -i $tar | Out-Null
    if ($LASTEXITCODE -ne 0) { Falha "Nao consegui carregar $tar"; Read-Host; exit 1 }
} else {
    Passo "Sem .tar na pasta; vou construir a imagem (precisa de internet)..."
    docker compose --project-directory $raiz build
    if ($LASTEXITCODE -ne 0) { Falha "A construcao falhou."; Read-Host; exit 1 }
}

# --- 3. Sobe o servico -----------------------------------------------------
Passo "Ligando o servico..."
docker compose --project-directory $raiz up -d
if ($LASTEXITCODE -ne 0) { Falha "Nao consegui subir o container."; Read-Host; exit 1 }

Passo "Esperando a aplicacao responder..."
$ok = $false
foreach ($tentativa in 1..60) {
    try {
        $r = Invoke-WebRequest 'http://localhost:8501/_stcore/health' -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { Start-Sleep -Seconds 2 }
}
if (-not $ok) { Falha "Subiu, mas nao respondeu em 2 minutos. Veja o Docker Desktop." }

# --- 4. Atalho na Area de Trabalho -----------------------------------------
# O IconFile precisa de caminho absoluto DESTA maquina, entao o .url e escrito
# aqui, na instalacao, e nao versionado pronto no repositorio.
Passo "Criando o atalho na Area de Trabalho..."
$icone = Join-Path $aqui 'transcricao.ico'
$mesa = [Environment]::GetFolderPath('Desktop')
$atalho = Join-Path $mesa 'AudioToText.url'

$conteudo = @"
[InternetShortcut]
URL=http://localhost:8501
IconFile=$icone
IconIndex=0
"@
[System.IO.File]::WriteAllText($atalho, $conteudo, [System.Text.UTF8Encoding]::new($false))

# O plano B vai como ATALHO .lnk, e nao como copia do .bat.
#
# Um .bat na Area de Trabalho carrega o icone generico de engrenagem do Windows:
# .bat nao guarda icone proprio. O .lnk guarda, entao o arquivo executavel fica
# na pasta de instalacao e so o atalho vai para a mesa -- com o icone da mesma
# familia do principal, para os dois parecerem o mesmo programa.
$planoB = Join-Path $mesa 'Se não abrir - clique aqui.lnk'
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($planoB)
$lnk.TargetPath = Join-Path $aqui 'Se nao abrir - clique aqui.bat'
$lnk.WorkingDirectory = $aqui
$lnk.IconLocation = (Join-Path $aqui 'transcricao-planoB.ico') + ',0'
$lnk.Description = 'Liga o AudioToText e espera ele responder'
$lnk.Save()

# Restos de instalacoes anteriores, para nao ficarem atalhos duplicados na mesa:
# o .bat que era copiado solto, e o .url com o nome que o programa tinha antes.
foreach ($resto in @('Se não abrir - clique aqui.bat', 'Transcrição de áudio.url')) {
    $caminho = Join-Path $mesa $resto
    if (Test-Path $caminho) { Remove-Item $caminho -Force }
}

Write-Host ""
Write-Host "  Pronto." -ForegroundColor Green
Write-Host "  Na Area de Trabalho tem o atalho 'AudioToText'." -ForegroundColor Green
Write-Host ""
Read-Host "  Enter para fechar"
