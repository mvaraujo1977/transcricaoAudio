@echo off
REM Instalador. Duplo clique aqui, uma vez so.
REM
REM Este .bat e uma casca fina: o trabalho esta no instalar.ps1 ao lado, porque
REM .bat e codepage do console nao lidam bem com acento, e o atalho precisa
REM nascer com o nome certo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
