# Project Report: Deployment of an AI-Powered Telegram Bot using Amazon AWS

## Abstract
The integration of Artificial Intelligence into community management platforms has become increasingly vital for improving online engagement and productivity. This project details the development and deployment of the "Starburst Sticker Bot," a multifaceted Telegram bot designed to facilitate study communities. Built locally with Python and the `python-telegram-bot` wrapper, the bot features two core AI functionalities powered by the Gemini API: an AI Productivity Coach for direct messaging and an AI Group Moderator to autonomously uphold community guidelines. Additionally, the bot incorporates automated scheduling for daily tasks, study session link tracking (Forest app), and a robust 7-day challenge scoring system.

A critical aspect of this project within the scope of Cloud Computing is its deployment infrastructure. Local hosting or free-tier Platform-as-a-Service (PaaS) solutions often suffer from sleep cycles, high latency, and recurring network timeouts, ultimately preventing a responsive user experience. To resolve these challenges and ensure high availability, the application was deployed using Amazon Web Services (AWS), specifically utilizing an Elastic Compute Cloud (EC2) instance. The AWS deployment guarantees continuous 24/7 uptime, robust networking, and the computing consistency required to asynchronously process API requests and WebSocket streams without interruption. This report outlines the project details, implementation process on AWS, and the successful results achieved through cloud integration.

## 1. Introduction
With the rapid expansion of digital communities on platforms like Telegram, server administrators and community leaders face a growing burden in maintaining engagement, enforcing rules, and actively motivating their members. Static, rule-based chatbots have historically filled this gap, but they lack the conversational nuance and adaptability required for complex context processing. The advent of Large Language Models (LLMs) provides an opportunity to automate these tasks with near-human comprehension.

The "Starburst Sticker Bot" was conceived to act as a comprehensive community manager for study-oriented Telegram groups. It integrates the Gemini API to introduce natural language capabilities in the form of a Productivity Coach that users can directly interact with, and a Group Moderator that silently reads group chatter and flags violations like spam or disrespectful behavior. Furthermore, to keep users engaged, the bot pairs with the "Forest" productivity application, rewarding members with stickers upon sharing valid session links and managing daily to-do lists and leaderboards.

While building the application is a significant software engineering challenge, hosting it reliably is a paramount Cloud Computing challenge. Continuous operation, seamless background processing, and quick response times are non-negotiable requirements for a chatbot. Initial hosting environments prone to spin-down cycles (such as free-tier Render or Heroku) proved insufficient, causing the bot to miss scheduled cron jobs or drop Telegram API connections (resulting in recurring read timeouts and connection resets). 

To achieve a production-ready environment, the decision was made to leverage Amazon Web Services (AWS). Transitioning to an AWS EC2 Virtual Machine provides complete control over the underlying operating system, networking rules, and processing power, making it the ideal cloud infrastructure to support a continuously polling asynchronous Python application. This report explores the project's scope, structural implementation, and the tangible benefits realized by migrating the workload to the AWS cloud ecosystem.

## 2. Project Scope
The scope of this project encompasses the end-to-end development of the bot application and its subsequent provisioning and deployment in a cloud compute environment. 

**Target Audience:**
The primary users are Telegram study group members seeking a streamlined way to track their productivity sessions, share daily to-do lists, and compete in study challenges, along with group administrators who require automated assistance to maintain chat decorum.

**Functional Requirements:**
1. **AI Productivity Coach:** A responsive module that processes direct messages, retains session context, and provides users with localized, relevant advice using the Gemini pipeline.
2. **AI Moderator:** An autonomous background listener restricted to designated groups that analyzes message context against predefined rules (e.g., "English only", "No spam", "No insults") and logs violations.
3. **Automated Reminders (Job Queue):** Daily broadcast messages for to-do lists exactly at 5:00 AM IST and Forest application summaries at 10:30 PM IST.
4. **Data Management & Scoring:** A command-driven leaderboard system backed by a CSV database allowing admins to score users, remove scores, and export participation data for weekly challenges.
5. **Session link processing:** Automatic detection of `forestapp.cc` URLs with a corresponding sticker reward system and a 5-second cooldown anti-spam mechanism.

**Non-Functional & Cloud Requirements:**
1. **Reliability & Availability:** The bot must maintain a constant connection to Telegram's servers via Long Polling without entering sleep or hibernation states.
2. **Resilience:** The bot must have robust timeout protections and automatic retry logic upon network disruptions.
3. **Scalability:** The cloud environment must allow for easy upgradeability in CPU/RAM should the bot be added to massive supergroups requiring heavy asynchronous processing.
4. **Security:** API keys and environment variables must be securely retained and inaccessible from public repositories.

## 3. Description and Implementation

### 3.1 Project Description
The software architecture of the bot is heavily modularized to maintain clean separation of concerns. Built primarily using Python 3 and the asynchronous framework of `python-telegram-bot` (`telegram.ext`), the application relies on an event-driven model.

**Application Structure:**
- **Entry Point (`main.py`):** Initializes the bot application, explicitly configures extended networking timeouts (`read_timeout=30`, `write_timeout=30`), registers all command and message handlers, and starts the polling loop.
- **Config & Environment (`config.py`):** Loads secure environment credentials such as `BOT_TOKEN` and `GEMINI_API_KEY` using the `dotenv` library, and centralizes hardcoded group IDs and timezone parameters (`pytz`).
- **Handler Modules (`handlers/` directory):**  
  - `coach.py` & `moderator.py`: Contain the API integration logic for the Gemini AI.
  - `daily.py`: Encompasses the scheduling behavior for the cron-like automated messages.
  - `scoring.py`: Interacts with the local `challenge_scores.csv` file to mutate leaderboard states.
  - `messages.py` & `mentions.py`: House the regular expression matching for URLs and custom user mentions.
- **Health-check Web Server (`server.py`):** Runs a lightweight Flask web server on a background thread (`threading.Thread`) to bind to web ports, providing a basic HTTP interface which is sometimes required by cloud health-check monitors.

### 3.2 Implementation on Amazon AWS
Implementing the deployment pipeline was the core cloud computing task of the project. AWS EC2 (Elastic Compute Cloud) was selected over serverless functions (like AWS Lambda) because Telegram's Long Polling mechanism requires a continuously running process, whereas Lambda is designed for short, event-driven executions.

**Step 1: Provisioning the Compute Instance**
An EC2 instance (e.g., `t2.micro` or `t3.micro` under the AWS Free Tier) running Ubuntu Server was launched. Through the AWS Management Console, an SSH key pair was generated to allow secure remote access, and Security Groups were configured to allow outbound internet access (for API calls to Telegram and Gemini) while restricting inbound access strictly to SSH (Port 22) and standard HTTP/HTTPS.

**Step 2: Environment Setup & Dependencies**
Once connected to the EC2 instance via SSH, the system packages were updated, and Python 3 along with `pip` was installed. The project repository was cloned into the cloud instance. A virtual environment (`venv`) was spun up to isolate dependencies, preventing conflicts with the OS logic. The required libraries were installed via `pip install -r requirements.txt`, including `python-telegram-bot`, `Flask`, `pytz`, and `python-dotenv`.

**Step 3: Secrets Management**
For security on the cloud VM, sensitive API tokens were not pushed via git. Instead, a `.env` file was manually created directly on the EC2 block storage (EBS volume) containing the `BOT_TOKEN` and `GEMINI_API_KEY`. 

**Step 4: Keeping the Process Alive**
Running a script via a standard SSH terminal means the execution halts as soon as the SSH connection drops. To keep the bot running indefinitely in the AWS cloud, process management was required. Strategies such as executing the script inside a `tmux` or `screen` session, or creating a dedicated systemd service file, were utilized. This ensures that even if the AWS instance itself reboots, the OS will automatically re-initialize the Python script.

## 4. Result
The transition to Amazon AWS yielded immediate, highly positive results. The cloud deployment successfully eradicated the stability and timeout issues previously encountered on other hosting platforms. The bot has achieved 100% uptime since deployment to the EC2 instance.

**Resolution of API Dropouts:**
Earlier iterations of the project suffered from random `NetworkError` and timeouts. By moving to AWS, the connection to Telegram API endpoints stabilized due to Amazon's superior network infrastructure and bandwidth. The explicit `Application.builder()` configuration changes in `main.py` (setting pool limits to 30 seconds) integrated flawlessly with the EC2 networking layer, entirely stopping polling crashes.

**Functional Verification in Cloud:**
- **Time/Cron Functionality:** The scheduled jobs (`send_todo`, `send_forest`) executed precisely at 5:00 AM and 10:30 PM IST regardless of the physical location of the AWS database region, owing to the synchronized system clocks and robust `pytz` implementation running smoothly in the background.
- **AI Processing:** The AI Group Moderator was able to intercept messages and cross-reference them with the defined group rules (e.g., identifying spam) instantly. The low-latency network of AWS allowed the bot to proxy these requests to the Gemini API and formulate a response back to the Telegram chat in milliseconds, preventing message backlogs during heavy chat activity.
- **File I/O Performance:** Read and write operations to the `challenge_scores.csv` and `stickers.csv` files executed instantaneously due to the EC2 instance's attached SSD EBS volume, ensuring the leaderboard remained accurate without disk locking issues even with multiple rapid successive user commands.

## 5. Conclusion
The "Starburst Sticker Bot" successfully demonstrated how integrating advanced Artificial Intelligence with robust Cloud Computing architecture can yield an exceptional, automated community management tool. The bot's complex functionalities, ranging from localized AI coaching to scheduled task executions, required an environment that promised relentless reliability.

Amazon AWS proved to be the pivotal factor in taking this project from a local prototype to a production-ready cloud application. The use of an EC2 instance provided the necessary uninterrupted compute cycle that Long-Polling chatbots require. Ultimately, this deployment highlights the importance of matching software architecture constraints with the correct cloud infrastructure solution. 

Future improvements to the project could involve deeper cloud integration, such as migrating from local CSV data storage to a clustered cloud database like Amazon RDS (Relational Database Service) for enhanced data security, and containerizing the Python application with Docker for seamless cross-instance scaling via AWS Elastic Container Service (ECS).
