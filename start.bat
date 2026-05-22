@echo off
cd /d C:\Users\vizva\controlroom-api
call venv\Scripts\activate
uvicorn main:app --reload
pause