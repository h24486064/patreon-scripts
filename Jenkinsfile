// Jenkinsfile (Declarative Pipeline - Windows Version)
pipeline {
    // 讓 Jenkins 自動分配可用的節點
    agent any

    // 環境變數設定 (確保 Python 輸出不會亂碼)
    environment {
        PYTHONIOENCODING = 'utf-8'
    }

    // 定時啟動觸發器 (每天半夜 2 點左右自動執行)
    triggers {
        cron('H 2 * * *') 
    }

    stages {
        stage('Setup Python Environment') {
            steps {
                echo '開始安裝 Python 依賴套件 (requirements.txt)...'
                // 在 Windows 環境下使用 bat (Batch) 執行指令
                bat '''
                    REM 切換為 UTF-8 編碼避免亂碼
                    chcp 65001 > nul
                    
                    REM 確保系統環境變數已有 python 與 pip
                    python -m pip install -r requirements.txt
                '''
            }
        }

        stage('Run Quick Tests') {
            steps {
                echo '執行爬蟲快速測試 (前 3 筆資料)...'
                bat '''
                    chcp 65001 > nul
                    
                    REM 執行 Python 腳本 (Windows 通常直接用 python 而不是 python3)
                    python Ver16.py 3 --headless
                '''
            }
        }

        // 預留完整爬蟲階段
        stage('Run Full Scrape') {
            when {
                expression { return false } // 暫時關閉
            }
            steps {
                echo '執行完整爬蟲...'
                bat '''
                    chcp 65001 > nul
                    python Ver16.py --headless
                '''
            }
        }
    }

    // 建置後的善後與通知
    post {
        always {
            echo 'Pipeline 執行結束，清空暫存或還原環境...'
            // 如果要在 Windows 清理 workspace，可以把下面這行取消註解
            // cleanWs() 
        }
        success {
            echo '爬蟲測試順利完成'
        }
        failure {
            echo '爬蟲測試失敗，請檢查 Console Output'
        }
    }
}