<#
  montar-pacote.ps1 - monta a pasta de entrega ao cliente

  ATENCAO: este arquivo e deliberadamente ASCII puro, sem acentos e sem
  travessoes. O Windows PowerShell 5.1 le arquivo .ps1 sem BOM como ANSI, e
  nesse caso caracteres UTF-8 multibyte podem produzir aspas tipograficas
  (0x93 / 0x94) - que o PowerShell aceita como delimitador de string. O parser
  entao fecha strings no lugar errado e falha com "Token '}' inesperado".
  Se quiser acentos aqui, salve o arquivo como UTF-8 COM BOM.

  Rode da RAIZ do repositorio transcricaoAudio:

      .\montar-pacote.ps1

  O que faz, em ordem:
    1. Clona o repositorio num diretorio temporario (clone limpo) e constroi a
       imagem ali. Isso existe para pegar a armadilha do CRLF: se o
       .gitattributes falhar, o container entra em loop de reinicio e o erro
       aparece AQUI, nao na maquina do cliente.
    2. Sobe um container de validacao (nome e porta proprios) e confere que
       ele fica de pe.
    3. Gera o .tar com docker save.
    4. Gera o PDF do guia.
    5. Copia so o que o cliente precisa para .\pacote-cliente\.
    6. Escreve o docker-compose.yml do cliente, sem a linha build.

  Parametros:
    -PularBuild     usa um .tar ja existente, nao reconstroi (teste rapido)
    -PularClone     constroi a partir da pasta atual, sem clone limpo
    -Destino <dir>  outra pasta de saida (padrao: .\pacote-cliente)
    -Tag <tag>      versao da imagem (padrao: 1.0)
#>

[CmdletBinding()]
param(
    [string]$Destino  = ".\pacote-cliente",
    [string]$Tag      = "1.0",
    [switch]$PularBuild,
    [switch]$PularClone
)

$ErrorActionPreference = "Stop"
$Imagem = "transcricao-audio:$Tag"

function Passo($t) { Write-Host "`n=== $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "  [ok] $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "  [!]  $t" -ForegroundColor Yellow }
function Erro($t)  { Write-Host "  [X]  $t" -ForegroundColor Red }

<#
  Executa um comando externo cujo stderr deve ser ignorado, e devolve o stdout.

  Por que isto existe: com $ErrorActionPreference = 'Stop', o Windows
  PowerShell 5.1 transforma QUALQUER linha que um programa externo escreva no
  stderr em erro TERMINANTE. O '2>$null' nao protege - ao contrario, e ele que
  converte a saida em registro de erro. Isso quebrava o
  'docker rm -f <container que nao existe>', cujo "No such container" e
  justamente o resultado esperado, e quebraria tambem a checagem do
  'docker info' com o Docker fechado.

  Aqui a preferencia e baixada apenas dentro do bloco, e o codigo de saida
  continua disponivel em $LASTEXITCODE para quem chamou.
#>
function Externo {
    param([scriptblock]$Bloco)
    $antigo = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try   { & $Bloco 2>$null }
    finally { $ErrorActionPreference = $antigo }
}

# --- Verificacoes de partida ---------------------------------------------

Passo "Verificando o ambiente"

$raiz = (Get-Location).Path
foreach ($f in @("docker-compose.yml", "Dockerfile", "cliente")) {
    if (-not (Test-Path (Join-Path $raiz $f))) {
        Erro "Nao encontrei '$f'. Rode este script da raiz do repositorio."
        exit 1
    }
}
Ok "Estou na raiz do repositorio"

# Programa externo que falha NAO lanca excecao: so escreve no stderr e devolve
# codigo de saida. Por isso o teste e no $LASTEXITCODE, nao num try/catch.
$versaoDocker = Externo { docker info --format '{{.ServerVersion}}' }
if ($LASTEXITCODE -ne 0) {
    Erro "O motor do Docker nao esta respondendo."
    Erro "Abra o Docker Desktop, espere ficar pronto, e rode de novo."
    exit 1
}
Ok "Docker respondendo (engine $versaoDocker)"

# --- 1 e 2. Build a partir de clone limpo --------------------------------

$tarOrigem = Join-Path $raiz "cliente\transcricao-audio.tar"

if ($PularBuild) {
    if (-not (Test-Path $tarOrigem)) {
        Erro "-PularBuild pedido, mas nao existe $tarOrigem"
        exit 1
    }
    Aviso "Build pulado. Usando o .tar existente, nao validado nesta rodada."
}
else {
    if ($PularClone) {
        $pastaBuild = $raiz
        Aviso "Clone limpo pulado. Construindo da pasta atual."
    }
    else {
        Passo "Clonando o repositorio num diretorio temporario"
        $pastaBuild = Join-Path $env:TEMP ("transcricao-build-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
        # Sem --depth: em clone local o Git ignora a opcao e ainda avisa.
        # O git escreve o progresso no stderr, por isso vai dentro de Externo.
        Externo { git clone $raiz $pastaBuild }
        if ($LASTEXITCODE -ne 0) { Erro "git clone falhou"; exit 1 }
        Ok "Clone limpo em $pastaBuild"
        Aviso "O clone usa os commits JA FEITOS. Alteracao nao commitada nao entra."
    }

    $nomeVal  = "transcricao-validacao"
    $portaVal = 8599

    Passo "Construindo a imagem $Imagem"
    Push-Location $pastaBuild
    try {
        docker compose build
        if ($LASTEXITCODE -ne 0) { Erro "docker compose build falhou"; exit 1 }
        Ok "Imagem construida"

        Passo "Subindo um container de validacao para conferir que ele fica de pe"

        # Nome e porta proprios, de proposito: o compose fixa container_name
        # 'transcricao' e a porta 8501, entao usar o compose aqui colidiria com
        # a instancia de desenvolvimento que ja esteja rodando na maquina.
        # Esta etapa valida a IMAGEM (entrypoint, CRLF), nao o compose.

        # Sobra de uma execucao anterior interrompida. Se nao existir, o docker
        # escreve "No such container" no stderr, o que aqui e normal.
        Externo { docker rm -f $nomeVal } | Out-Null

        Externo { docker run -d --name $nomeVal -p "127.0.0.1:${portaVal}:8501" $Imagem } | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Erro "docker run falhou. A porta $portaVal pode estar ocupada."
            exit 1
        }

        Start-Sleep -Seconds 20

        $estado   = Externo { docker inspect -f '{{.State.Status}}' $nomeVal }
        $restarts = Externo { docker inspect -f '{{.RestartCount}}' $nomeVal }

        if ($estado -ne "running") {
            Erro "O container de validacao nao esta 'running' (estado: $estado)."
            Erro "Se estiver reiniciando, o suspeito principal e CRLF no entrypoint.sh."
            Write-Host "`nUltimas linhas do log:" -ForegroundColor Yellow
            Externo { docker logs --tail 30 $nomeVal }
            Externo { docker rm -f $nomeVal } | Out-Null
            exit 1
        }
        if ([int]$restarts -gt 0) {
            Aviso "O container reiniciou $restarts vez(es). Confira o log antes de entregar."
            Externo { docker logs --tail 20 $nomeVal }
        }
        Ok "Container de pe (estado: $estado, reinicios: $restarts)"
        Aviso "Abra http://localhost:$portaVal e transcreva um arquivo curto ANTES de continuar."
        Aviso "Note a porta ${portaVal}: e a da validacao, nao a 8501 do seu ambiente."
        Read-Host "  Funcionou? Enter para seguir, Ctrl+C para abortar"

        Externo { docker rm -f $nomeVal } | Out-Null
        Ok "Container de validacao removido"
    }
    finally { Pop-Location }

    Passo "Gerando o .tar com docker save"
    Externo { docker save $Imagem -o $tarOrigem }
    if ($LASTEXITCODE -ne 0) { Erro "docker save falhou"; exit 1 }
    $mb = [math]::Round((Get-Item $tarOrigem).Length / 1MB, 0)
    Ok "$tarOrigem gerado ($mb MB)"

    if (-not $PularClone -and (Test-Path $pastaBuild)) {
        Remove-Item $pastaBuild -Recurse -Force -ErrorAction SilentlyContinue
        Ok "Diretorio temporario removido"
    }
}

# --- 3. PDF do guia -------------------------------------------------------

Passo "Gerando o PDF do guia"

$gerador = Join-Path $raiz "cliente\gerar_guia_pdf.py"
if (Test-Path $gerador) {
    Externo { python $gerador }
    if ($LASTEXITCODE -eq 0) { Ok "gerar_guia_pdf.py executado" }
    else { Aviso "gerar_guia_pdf.py terminou com erro. Gere o PDF a mao." }
}
else { Aviso "Nao encontrei cliente\gerar_guia_pdf.py" }

$pdf = Get-ChildItem -Path $raiz -Filter "*.pdf" -Recurse -ErrorAction SilentlyContinue |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1

# --- 4. Montando a pasta de entrega --------------------------------------

Passo "Montando a pasta de entrega"

if (Test-Path $Destino) {
    Remove-Item $Destino -Recurse -Force
    Ok "Pasta anterior removida"
}
New-Item -ItemType Directory -Path $Destino | Out-Null
$Destino = (Resolve-Path $Destino).Path

# Copia binaria, para o BOM do instalar.ps1 e os .ico chegarem intactos.
$doCliente = @(
    "instalar.bat",
    "instalar.ps1",
    "Se nao abrir - clique aqui.bat",
    "transcricao.ico",
    "transcricao-planoB.ico",
    "transcricao-audio.tar"
)

foreach ($nome in $doCliente) {
    $origem = Join-Path $raiz "cliente\$nome"
    if (Test-Path $origem) {
        Copy-Item $origem -Destination $Destino
        Ok "$nome"
    }
    else { Aviso "FALTANDO: cliente\$nome" }
}

# Geradores NAO vao: sao ferramentas suas, e exigiriam Python na maquina dele.
foreach ($nome in @("gerar_icones.py", "gerar_guia_pdf.py")) {
    if (Test-Path (Join-Path $raiz "cliente\$nome")) { Ok "$nome deixado de fora (correto)" }
}

if ($pdf) {
    Copy-Item $pdf.FullName -Destination (Join-Path $Destino "Guia de uso.pdf")
    Ok "Guia de uso.pdf (copiado de $($pdf.Name))"
}
else { Aviso "FALTANDO: o PDF do guia. Gere e copie como 'Guia de uso.pdf'." }

# --- 5. docker-compose.yml do cliente ------------------------------------

Passo "Escrevendo o docker-compose.yml do cliente"

# Filtra a linha build. Na maquina do cliente nao ha codigo-fonte, e um
# docker compose up --build acidental tentaria construir e falharia.
$linhas   = Get-Content (Join-Path $raiz "docker-compose.yml")
$filtrado = $linhas | Where-Object { $_ -notmatch '^\s*build\s*:' }

if ($linhas.Count -eq $filtrado.Count) { Aviso "Nao havia linha build para remover" }
else { Ok "Linha build removida" }

$semBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines((Join-Path $Destino "docker-compose.yml"), $filtrado, $semBom)
Ok "docker-compose.yml escrito (UTF-8 sem BOM)"

# Pasta onde os arquivos da CLI ficam. O volume ./dados do compose aponta aqui.
New-Item -ItemType Directory -Path (Join-Path $Destino "dados") | Out-Null

$comBom = New-Object System.Text.UTF8Encoding($true)

$leiaDados = "Os arquivos de audio que voce quiser transcrever pela linha de`r`n" +
             "comando podem ser colocados nesta pasta.`r`n`r`n" +
             "Se voce usa apenas a tela no navegador, nao precisa mexer aqui.`r`n"
[System.IO.File]::WriteAllText((Join-Path $Destino "dados\LEIA-ME.txt"), $leiaDados, $comBom)
Ok "pasta dados criada"

$aviso = "NAO MOVA NEM RENOMEIE ESTA PASTA`r`n" +
         "================================`r`n`r`n" +
         "O atalho na Area de Trabalho aponta para os arquivos que estao aqui`r`n" +
         "dentro. Se esta pasta for movida, renomeada ou apagada, o atalho para`r`n" +
         "de funcionar.`r`n`r`n" +
         "Local recomendado: C:\Transcricao`r`n`r`n" +
         "Como usar: leia o arquivo 'Guia de uso.pdf'.`r`n"
[System.IO.File]::WriteAllText((Join-Path $Destino "IMPORTANTE - nao mova esta pasta.txt"), $aviso, $comBom)
Ok "aviso sobre nao mover a pasta"

# --- Resumo ---------------------------------------------------------------

Passo "Pacote montado"

Write-Host "  $Destino`n" -ForegroundColor White
Get-ChildItem $Destino | ForEach-Object {
    if ($_.PSIsContainer) { "    {0,-40} <pasta>" -f $_.Name }
    else { "    {0,-40} {1,8:N1} MB" -f $_.Name, ($_.Length / 1MB) }
}

$total = [math]::Round(((Get-ChildItem $Destino -Recurse -File |
          Measure-Object Length -Sum).Sum / 1MB), 0)
Write-Host "`n  Total: $total MB" -ForegroundColor White

Write-Host "`nAntes de levar:" -ForegroundColor Gray
Write-Host "  1. Abra instalar.ps1 no Bloco de Notas e confira os acentos." -ForegroundColor Gray
Write-Host "     Se aparecer TranscriCAO estranho, o BOM se perdeu na copia." -ForegroundColor Gray
Write-Host "  2. Copie a pasta para o pen drive e teste A PARTIR DO PEN DRIVE." -ForegroundColor Gray
Write-Host "  3. Imprima o roteiro de teste e o Guia de uso.`n" -ForegroundColor Gray
