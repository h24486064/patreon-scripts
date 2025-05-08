// Jenkinsfile (Declarative Pipeline)

pipeline {
    // 指定在哪個 Jenkins Agent (節點) 上執行此 Pipeline
    // 如果你的爬蟲需要在特定的 Windows 環境執行，且該 Agent 已設定好，你可以這樣指定：
    // agent { label 'your-windows-agent-label' }
    // 否則，使用 any 讓 Jenkins 自動分配可用的 Agent
    agent any // 或者 agent { label 'windows' } 如果你有標記為 'windows' 的 Agent

    // 設定 Pipeline 範圍內的環境變數 (可選，也可以在 steps 裡面設定)
    environment {
        // 設定 Python I/O 編碼
        PYTHONIOENCODING = 'utf-8'
    }

        stage('Setup Python Environment') {
            steps {
                echo 'Setting up Python environment and installing dependencies...'
                // 這裡我們使用 bat step 來執行 Windows 命令
                // Jenkins 在執行 Pipeline 時，會自動將程式碼 checkout 到一個工作目錄 (workspace)
                // 假設你的 requirements.txt 就在這個工作目錄的根部
                bat '''
                    REM 設定字元編碼
                    chcp 65001 > nul
                    REM PYTHONIOENCODING 已在 environment block 設定，這裡可以省略，
                    REM 或者為了保險再次設定也可以。
                    REM set PYTHONIOENCODING=utf-8

                    REM 使用 pip 安裝 requirements.txt 中列出的依賴
                    REM 確保你的 Jenkins Agent 上已經安裝了 Python 和 pip，並且在 PATH 中
                    pip install -r requirements.txt
                '''
                // 如果你的 Jenkins Agent 可能在 Linux 或 macOS 上，
                // 你需要使用 sh step 並使用相應的命令 (export 而非 set, pip3 或其他 Python 版本命令)
                // sh '''
                //     export PYTHONIOENCODING=utf-8
                //     pip install -r requirements.txt
                // '''
            }
        }

        stage('Run Quick Tests') {
            steps {
                echo 'Running quick tests (first 3 URLs)...'
                // 使用 bat step 來執行你的測試命令
                // Jenkins 的 bat step 會在工作的 workspace 目錄中執行命令，
                // 所以如果你 Ver16.py 在倉庫的根目錄，就不需要像批次檔那樣額外 cd 了。
                // 如果 Ver16.py 在子目錄中 (例如 src/)，你可以使用 dir('src') { bat 'python Ver16.py ...' }
                bat '''
                    REM 設定字元編碼 (如果已在 Setup Stage 設定，這裡可以省略)
                    chcp 65001 > nul
                    REM PYTHONIOENCODING 已在 environment block 設定，這裡可以省略。
                    REM set PYTHONIOENCODING=utf-8

                    REM 執行你的 Python 測試腳本
                    REM 假設 Ver16.py 在程式碼倉庫根目錄
                    python Ver16.py 3 --headless
                    REM Jenkins 的 bat step 會自動捕獲命令的 exit code，
                    REM 如果 exit code 非 0，Jenkins 會標記此步驟失敗，進而導致 Stage 和建置失敗。
                    REM 所以你批次檔中的 exit /b %errorlevel% 在這裡是不需要的。
                '''
                 // 如果你的 Jenkins Agent 可能在 Linux 或 macOS 上
                 // sh '''
                 //     export PYTHONIOENCODING=utf-8
                 //     python Ver16.py 3 --headless
                 // '''
            }
        }

        // --- 定時觸發的正式爬蟲流程 (暫時先不處理這部分，後面再加) ---
        // stage('Setup Environment (Full Run)') { ... }
        // stage('Run Full Scrape') { ... }
        // stage('Upload Results to Google Cloud') { ... }
    }

    // 建置後動作 (例如：發送通知)
    post {
        always {
            echo 'Pipeline finished.'
        }
        success {
            echo 'Quick tests passed!'
            // mail to: 'your-email@example.com', subject: "CI Tests Passed: ${currentBuild.fullDisplayName}"
        }
        failure {
            echo 'Quick tests failed!'
            // mail to: 'your-email@example.com', subject: "CI Tests Failed: ${currentBuild.fullDisplayName}"
        }
    }

