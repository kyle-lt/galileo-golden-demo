"""
Galileo API Helper Functions

These helpers load only the API key and console URL from secrets.
Domain-specific environment setup (like project names) is handled by the main app.
"""
import requests
import logging
import os
import toml
from pathlib import Path


def _load_secrets_if_needed():
    """
    Load secrets from .streamlit/secrets.toml if environment variables are not set.
    Only loads API key and console URL (not domain-specific settings).
    """
    # Check if already loaded
    if os.environ.get("GALILEO_API_KEY") and os.environ.get("GALILEO_CONSOLE_URL"):
        return
    
    # Find secrets file
    secrets_path = Path(__file__).parent.parent / ".streamlit" / "secrets.toml"
    
    if not secrets_path.exists():
        return
    
    try:
        secrets = toml.load(secrets_path)
        
        # Set only the non-domain-specific environment variables
        if "galileo_api_key" in secrets and not os.environ.get("GALILEO_API_KEY"):
            os.environ["GALILEO_API_KEY"] = secrets["galileo_api_key"]
        
        if "galileo_console_url" in secrets and not os.environ.get("GALILEO_CONSOLE_URL"):
            os.environ["GALILEO_CONSOLE_URL"] = secrets["galileo_console_url"]
            
    except Exception as e:
        logging.warning(f"Could not load secrets: {e}")


def get_galileo_app_url() -> str:
    """
    Get the Galileo web console URL from environment variables.
    
    Returns:
        str: The Galileo web console URL without trailing slash
        
    Raises:
        ValueError: If GALILEO_CONSOLE_URL is not set
    """
    _load_secrets_if_needed()
    
    galileo_url = os.environ.get("GALILEO_CONSOLE_URL")
    if not galileo_url:
        raise ValueError("GALILEO_CONSOLE_URL environment variable is not set")
    
    # Remove trailing slash if present
    return galileo_url.rstrip('/')


def get_galileo_api_url() -> str:
    """
    Get the Galileo API URL from environment variables.
    
    Returns:
        str: The Galileo API URL
        
    Raises:
        ValueError: If GALILEO_CONSOLE_URL is not set
    """
    galileo_url = get_galileo_app_url()
    
    # Extract domain without protocol
    if galileo_url.startswith("https://"):
        domain = galileo_url[8:]  # Remove https://
    elif galileo_url.startswith("http://"):
        domain = galileo_url[7:]  # Remove http://
    else:
        domain = galileo_url
    
    # Remove app. prefix if exists and any path components
    if domain.startswith("app."):
        domain = domain[4:]
    domain = domain.split('/')[0]  # Get just the domain part
    
    return f"https://api.{domain}"


def get_galileo_api_key() -> str:
    """
    Get the Galileo API key from environment variables.
    
    Returns:
        str: The Galileo API key
        
    Raises:
        ValueError: If GALILEO_API_KEY is not set
    """
    _load_secrets_if_needed()
    
    api_key = os.environ.get("GALILEO_API_KEY")
    if not api_key:
        raise ValueError("GALILEO_API_KEY environment variable is not set")
    return api_key


def _resolve_galileo_project_id(project_name: str) -> str | None:
    """Resolve a project ID by name via REST pagination and SDK list fallback."""
    project_id = get_galileo_project_id(project_name)
    if project_id:
        return project_id

    try:
        from galileo.projects import Projects

        for project in Projects().list() or []:
            if getattr(project, "name", None) == project_name:
                return project.id
    except Exception as exc:
        logging.debug("SDK project list failed: %s", exc)

    return None


def get_galileo_project_id(project_name: str, starting_token: int = 0, limit: int = 100) -> str | None:
    """
    Fetches the Galileo project ID for a given project name.

    Args:
        project_name (str): The name of the project to search for.
        starting_token (int): The starting token for pagination.
        limit (int): The number of projects to fetch.

    Returns:
        str: The project ID if found, else None.
        
    Raises:
        ValueError: If required environment variables are not set
        requests.RequestException: If API request fails
    """
    api_key = get_galileo_api_key()
    galileo_url = get_galileo_app_url()
    headers = {
        "accept": "*/*",
        "galileo-api-key": api_key,
        "content-type": "application/json",
        "origin": galileo_url,
        "referer": f"{galileo_url}/",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    }
    data = {
        "sort": {"name": "updated_at", "ascending": False},
        "filters": [],
    }

    token = starting_token
    while True:
        url = f"{galileo_url}/api/galileo/public/v2/projects/paginated?starting_token={token}&limit={limit}"
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        for project in result.get("projects", []):
            if project.get("name") == project_name:
                return project.get("id")
        next_token = result.get("next_starting_token")
        if next_token is None:
            return None
        token = next_token


def create_galileo_logger(project_name: str, log_stream: str):
    """
    Create a GalileoLogger for a project/log stream.

    Resolves or creates the project explicitly so the SDK never falls back to
    ``GalileoLogger(project=...)`` when a same-named project exists in the org
    but is not visible to this API key.
    """
    from galileo import GalileoLogger
    from galileo.projects import Projects

    project_id = _resolve_galileo_project_id(project_name)
    if not project_id:
        try:
            created = Projects().create(name=project_name)
            project_id = created.id
        except Exception as exc:
            if "already exists" in str(exc).lower():
                raise ValueError(
                    f"Galileo project '{project_name}' already exists in your organization "
                    "but is not accessible with your API key (likely missing collaborator access). "
                    "Set GALILEO_PROJECT in .env to a unique name (e.g. galileo-demo-yourname), "
                    "then run: ./scripts/demo.sh setup && ./scripts/demo.sh start"
                ) from exc
            raise

    log_stream_id = get_galileo_log_stream_id(project_id, log_stream)
    if log_stream_id:
        return GalileoLogger(project_id=project_id, log_stream_id=log_stream_id)
    return GalileoLogger(project_id=project_id, log_stream=log_stream)


def get_galileo_log_stream_id(project_id: str, log_stream_name: str) -> str:
    """
    Fetches the Galileo log stream ID for a given project ID and log stream name.

    Args:
        project_id (str): The ID of the project.
        log_stream_name (str): The name of the log stream to search for.

    Returns:
        str: The log stream ID if found, else None.
        
    Raises:
        ValueError: If required environment variables are not set
        requests.RequestException: If API request fails
    """
    api_key = get_galileo_api_key()
    galileo_url = get_galileo_app_url()
    
    url = f"{galileo_url}/api/galileo/v2/projects/{project_id}/log_streams"
    headers = {
        "accept": "*/*",
        "galileo-api-key": api_key,
        "content-type": "application/json",
        "origin": galileo_url,
        "referer": f"{galileo_url}/",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    log_streams = response.json()  # This is now a list of log streams
    
    for stream in log_streams:  # Iterate directly over the list
        if stream.get("name") == log_stream_name:
            return stream.get("id")
    return None
