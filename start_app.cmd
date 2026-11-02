@echo off
rem Startet den RS485-TCP Monitor ohne Konsolenfenster.
cd /d "%~dp0"
start "" pyw app.py
