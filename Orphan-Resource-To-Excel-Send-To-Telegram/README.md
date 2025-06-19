# How to use the script

1. Git clone the scripts
2. Edit var
```
OPENRC_PATH = '/path/to/rcfile'
OUTPUT_BASE_DIR = '/path/to/output/dir'
BOT_TOKEN = "telegram_bot_token"
CHAT_ID = "telegram_chat_id"
LOG_FILE_PATH = '/path/to/log/dir'
```
*Make sure u give the right path where the overcloudrc file*

3. Install pandas, openpyxl and xlsxwriter to combined file csv
```
pip install pandas openpyxl xlsxwriter
```

atau
```
pip install -r requirements.txt
```
4. running command "python main.py"
5. the output will have two type file, {object}.csv and orphan-resource-report.xlsx.
