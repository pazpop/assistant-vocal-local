@echo off
REM Double-cliquable : les .ps1 ne le sont jamais par defaut sous Windows
REM (securite), ce petit .bat sert juste a lancer install.ps1 correctement,
REM sans avoir besoin d'ouvrir PowerShell ni de connaitre son ExecutionPolicy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
pause
