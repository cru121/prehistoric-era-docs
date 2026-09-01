@echo off
REM Rebuild the docs from the live mod, then snapshot the mod into backup\.
REM Both steps auto-detect the live Steam Workshop copy; pass --mod "path" to
REM override (it is forwarded to both scripts).
setlocal
cd /d "%~dp0"

python generator\generate.py %*
if errorlevel 1 (
  echo.
  echo generate.py failed - skipping backup.
  exit /b 1
)

python generator\backup_mod.py %*
endlocal
