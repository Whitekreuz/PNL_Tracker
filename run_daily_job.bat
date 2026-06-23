@echo off
cd /d d:\datasci\PNL日志

echo [%date% %time%] Starting daily job...
D:\miniconda3\envs\quant\python.exe daily_job.py

echo [%date% %time%] Restarting Streamlit server...
:: 使用 wmic 安全地杀死可能冲突的 python 进程
wmic process where "commandline like '%streamlit run app.py%'" call terminate >nul 2>&1
wscript.exe start_app.vbs
