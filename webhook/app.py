from flask import Flask, request, jsonify
import os
import subprocess
import requests
import git
import shutil  # to copy entire directories
from environs import Env


env = Env()
env.read_env()


# Retrieve environment variables
GITHUB_TOKEN = env("MY_GITHUB_TOKEN")
# print(GITHUB_TOKEN)


app = Flask(__name__)


# Define variables for repository URLs
TESTS_REPO=f"https://{GITHUB_TOKEN}@github.com/PSEMPIRE/test_repo.git"
DJANGO_REPO = f"https://{GITHUB_TOKEN}@github.com/PSEMPIRE/Inventory_App.git"
# Webhook listener endpoint
@app.route("/webhook", methods=["POST"])
def webhook_listener():
    data = request.json
    if data.get("action") in ["opened", "synchronize"]:  # PR events
        pr_number = data["number"]
        handle_pr(pr_number)
    return jsonify({"message": "Received"}), 200

def handle_pr(pr_number):

    repo_dir = "/tmp/django-repo"

    # Remove directory if it exists
    if os.path.exists(repo_dir):
        subprocess.run(["rm", "-rf", repo_dir])

    try:
        # Clone the private Django repo
        git.Repo.clone_from(DJANGO_REPO, repo_dir)
        print("Repository cloned successfully.")
        django_project_path = os.path.join(repo_dir, "inventory")

        # Run tests with coverage and pytest to generate reports
        run_tests(django_project_path)
        
        # Push test results and comment on the PR
        push_results(pr_number)
    except Exception as e:
        print(f"Error cloning repository: {e}")
        return jsonify({"message": "Failed to clone repository"}), 500

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
            ["pytest", "--ds=inventory.settings", "--html=report.html"],
            cwd=django_project_path,
            check=True
        )
        print("Test report generated successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error running tests: {e}")



def push_results(pr_number):
    # Directory where the tests repo will be cloned
    tests_repo_dir = "/tmp/tests-repo"
    
    # Remove directory if it exists
    if os.path.exists(tests_repo_dir):
        subprocess.run(["rm", "-rf", tests_repo_dir])
    
    try:
        # Clone the tests repo
        git.Repo.clone_from(TESTS_REPO, tests_repo_dir, branch="gh-pages")
        print("Tests repository cloned successfully.")
        
        # Create a unique directory for the PR within the tests repo
        pr_dir = os.path.join(tests_repo_dir, f"pr-{pr_number}")
        os.makedirs(pr_dir, exist_ok=True)

        # Copy index.html (coverage report), report.html (pytest report), and the entire assets folder to the PR-specific directory
        index_html_source = os.path.join("/tmp/django-repo/inventory/htmlcov/index.html")
        index_html_destination = os.path.join(pr_dir, "index.html")
        report_html_source = os.path.join("/tmp/django-repo/inventory/report.html")
        report_html_destination = os.path.join(pr_dir, "report.html")
        assets_source = os.path.join("/tmp/django-repo/inventory/assets") 
        assets_destination = os.path.join(pr_dir, "assets")  # This will copy the 'assets' folder inside the pr-{pr_number} directory
        
        # Check if the source files exist before copying
        if os.path.exists(index_html_source) and os.path.exists(report_html_source) and os.path.exists(assets_source):
            # Copy the HTML files and the assets folder
            subprocess.run(["cp", index_html_source, index_html_destination])
            subprocess.run(["cp", report_html_source, report_html_destination])
            
            # Ensure assets folder gets copied properly
            if os.path.isdir(assets_source):
                shutil.copytree(assets_source, assets_destination)  # Copy the entire 'assets' folder
                print(f"Assets folder copied to: {assets_destination}")
            else:
                print("Assets folder not found.")
                return

            print(f"Reports and assets copied to PR-specific directory: {pr_dir}")
        else:
            print("One or more files (reports or assets) not found.")
            return

        # Commit and push the changes to gh-pages branch
        repo = git.Repo(tests_repo_dir)
        repo.index.add([f"pr-{pr_number}/index.html", f"pr-{pr_number}/report.html", f"pr-{pr_number}/assets"])
        repo.index.commit(f"Update reports and assets for PR #{pr_number}")
        repo.remotes.origin.push("gh-pages")
        print("Coverage report, test report, and assets folder pushed to tests repo successfully.")
        
        # Construct the URLs to the reports and assets in GitHub Pages
        coverage_url = f"https://psempire.github.io/test_repo/pr-{pr_number}/index.html"
        test_report_url = f"https://psempire.github.io/test_repo/pr-{pr_number}/report.html"
        assets_url = f"https://psempire.github.io/test_repo/pr-{pr_number}/assets/style.css"
        
        # Post a comment on the PR with the URLs to the reports and style.css
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
    comment_url = f"https://api.github.com/repos/PSEMPIRE/Inventory_App/issues/{pr_number}/comments"
    
    response = requests.post(comment_url, json={"body": comment_body}, headers=headers)
    
    if response.status_code == 201:
        print("Comment posted successfully.")
    else:
        print(f"Failed to post comment: {response.status_code} - {response.text}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
    

