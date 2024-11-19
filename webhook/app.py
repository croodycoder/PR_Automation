from flask import Flask, request, jsonify
import os
import subprocess
import requests
import git
import threading
import queue
import shutil  # to copy entire directories
from environs import Env

env = Env()
env.read_env()

# Retrieve environment variables
GITHUB_TOKEN = env("MY_GITHUB_TOKEN")
TESTS_REPO = env("TESTS_REPO")
DJANGO_REPO = env("DJANGO_REPO")
COVERAGE_BASE_URL = env("COVERAGE_BASE_URL")
COMMENT_BASE_URL = env("COMMENT_BASE_URL")
DJANGO_PROJECT_NAME = env("DJANGO_PROJECT_NAME")

app = Flask(__name__)

# Define variables for repository URLs


TESTS_REPO = TESTS_REPO.replace("https://", f"https://{GITHUB_TOKEN}@")
DJANGO_REPO = DJANGO_REPO.replace("https://", f"https://{GITHUB_TOKEN}@")

# Task queue and worker thread
task_queue = queue.Queue()


def worker():
    """Worker thread that processes tasks from the queue."""
    while True:
        pr_number = task_queue.get()
        if pr_number is None:
            break  # Exit the loop if sentinel None is received
        print(f"Processing PR #{pr_number}...")
        try:
            handle_pr(pr_number)
        except Exception as e:
            print(f"Error handling PR #{pr_number}: {e}")
        finally:
            task_queue.task_done()


# Start the worker thread
worker_thread = threading.Thread(target=worker, daemon=True)
worker_thread.start()


@app.route("/webhook", methods=["POST"])
def webhook_listener():
    data = request.json
    if data.get("action") in ["opened", "synchronize"]:  # PR events
        pr_number = data["number"]
        print(f"Webhook received for PR #{pr_number}. Adding to queue.")
        task_queue.put(pr_number)
    return jsonify({"message": "Received"}), 200


def handle_pr(pr_number):
    repo_dir = f"/tmp/django-repo-pr-{pr_number}"

    # Remove directory if it exists
    if os.path.exists(repo_dir):
        subprocess.run(["rm", "-rf", repo_dir])

    try:
        # Clone the private Django repo
        git.Repo.clone_from(DJANGO_REPO, repo_dir)
        print("Repository cloned successfully.")
        django_project_path = os.path.join(repo_dir, DJANGO_PROJECT_NAME)

        # Run tests with coverage and pytest to generate reports
        run_tests(django_project_path)

        # Push test results and comment on the PR
        push_results(pr_number)

    except Exception as e:
        print(f"Error cloning repository: {e}")


def run_tests(django_project_path):
    try:
        # Install dependencies for both coverage and pytest
        subprocess.run(["pip", "install", "coverage", "pytest", "pytest-django", "pytest-html"], check=True)

        # Run Django tests with coverage and generate the HTML coverage report
        subprocess.run(
            ["coverage", "run", "--source=.", "manage.py", "test"],
            cwd=django_project_path,
            check=True
        )
        subprocess.run(
            ["coverage", "html", "--directory=htmlcov"],
            cwd=django_project_path,
            check=True
        )
        print("Coverage HTML report generated successfully.")

        # Run pytest with Django settings and generate report.html
        subprocess.run(
            ["pytest", f"--ds={DJANGO_PROJECT_NAME}.settings", "--html=report.html"],
            cwd=django_project_path,
            check=True
        )
        print("Test report generated successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error running tests: {e}")


def push_results(pr_number):
    tests_repo_dir = f"/tmp/tests-repo-pr-{pr_number}"

    # Remove directory if it exists
    if os.path.exists(tests_repo_dir):
        subprocess.run(["rm", "-rf", tests_repo_dir])

    try:
        git.Repo.clone_from(TESTS_REPO, tests_repo_dir, branch="gh-pages")
        print("Tests repository cloned successfully.")

        pr_dir = os.path.join(tests_repo_dir, f"pr-{pr_number}")
        os.makedirs(pr_dir, exist_ok=True)

        index_html_source = os.path.join(f"/tmp/django-repo-pr-{pr_number}/{DJANGO_PROJECT_NAME}/htmlcov/index.html")
        index_html_destination = os.path.join(pr_dir, "index.html")
        report_html_source = os.path.join(f"/tmp/django-repo-pr-{pr_number}/{DJANGO_PROJECT_NAME}/report.html")
        report_html_destination = os.path.join(pr_dir, "report.html")
        assets_source = os.path.join(f"/tmp/django-repo-pr-{pr_number}/{DJANGO_PROJECT_NAME}/assets")
        assets_destination = os.path.join(pr_dir, "assets")

        if os.path.exists(index_html_source) and os.path.exists(report_html_source) and os.path.exists(assets_source):
            shutil.copy(index_html_source, index_html_destination)
            shutil.copy(report_html_source, report_html_destination)
            shutil.copytree(assets_source, assets_destination)
        else:
            print("One or more files missing for PR reports.")
            return

        repo = git.Repo(tests_repo_dir)
        repo.index.add([f"pr-{pr_number}/index.html", f"pr-{pr_number}/report.html", f"pr-{pr_number}/assets"])
        repo.index.commit(f"Update reports for PR #{pr_number}")
        repo.remotes.origin.push("gh-pages")

        coverage_url = f"{COVERAGE_BASE_URL}/pr-{pr_number}/index.html"
        test_report_url = f"{COVERAGE_BASE_URL}/pr-{pr_number}/report.html"
        assets_url = f"{COVERAGE_BASE_URL}/pr-{pr_number}/assets/style.css"

        post_comment(pr_number, coverage_url, test_report_url, assets_url)

    except Exception as e:
        print(f"Error in push_results: {e}")


def post_comment(pr_number, coverage_url, test_report_url, assets_url):
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    comment_body = (
        f"Coverage report available at: {coverage_url}\n\n"
        f"Test report available at: {test_report_url}\n\n"
        f"Style file available at: {assets_url}"
    )
    comment_url = f"{COMMENT_BASE_URL}/{pr_number}/comments"

    response = requests.post(comment_url, json={"body": comment_body}, headers=headers)

    if response.status_code == 201:
        print("Comment posted successfully.")
    else:
        print(f"Failed to post comment: {response.status_code} - {response.text}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)