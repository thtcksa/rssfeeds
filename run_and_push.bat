@echo off
cd /d "%~dp0"

echo Running scraper...
docker run --rm -v "%cd%":/app -w /app mcr.microsoft.com/playwright/python:v1.62.0-jammy bash -c "pip install beautifulsoup4 playwright requests -q && python combined_rss.py" > run_log.txt 2>&1

echo.
echo Pushing to GitHub...
git add .
git commit -m "Auto-update feed"
git push

echo.
echo Done.
pause