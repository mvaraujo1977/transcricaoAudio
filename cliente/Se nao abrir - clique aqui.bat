@echo off
REM Plano B do atalho da Area de Trabalho.
REM
REM O atalho normal e um .url: so abre o navegador. Se voce acabou de ligar o
REM computador, o Docker pode ainda estar acordando e a pagina de erro aparece.
REM Este arquivo liga o servico e espera ele responder antes de abrir a tela.
REM
REM Os programas do Windows sao chamados pelo caminho completo de proposito:
REM chamados so pelo nome, `timeout` e `curl` podem cair numa versao de outro
REM programa que esteja no PATH (Git, WSL, MSYS) e se comportar diferente.
REM Aconteceu num teste: o `timeout` do Git Bash respondeu "invalid time
REM interval /t".
title Transcricao de audio
setlocal

set "ESPERAR=%SystemRoot%\System32\ping.exe"
set "CURL=%SystemRoot%\System32\curl.exe"

echo.
echo   Ligando a Transcricao de audio...
echo   Pode levar ate um minuto na primeira vez do dia.
echo.

docker start transcricao >nul 2>&1
if errorlevel 1 goto semdocker

REM Sem curl (Windows anterior a 2018), espera um tempo fixo e abre assim mesmo:
REM se ainda nao estiver pronto, um F5 no navegador resolve.
if not exist "%CURL%" (
    "%ESPERAR%" -n 21 127.0.0.1 >nul
    goto abrir
)

set /a tentativas=0
:esperar
set /a tentativas+=1
"%CURL%" -s -o nul --max-time 3 http://localhost:8501/_stcore/health && goto abrir
if %tentativas% GEQ 45 goto desistir
"%ESPERAR%" -n 3 127.0.0.1 >nul
goto esperar

:abrir
start "" "http://localhost:8501"
exit /b 0

:semdocker
echo   Nao encontrei o servico neste computador.
goto ajuda

:desistir
echo.
echo   O servico ligou, mas nao respondeu a tempo.

:ajuda
echo.
echo   Abra o programa Docker Desktop (icone de baleia azul), espere
echo   a baleia parar de se mexer, e clique aqui de novo.
echo.
pause
exit /b 1
