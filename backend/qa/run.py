"""Ejecutor Windows para suites locales y servicios que pertenezcan a QA."""
import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from qa.environment import HOST, PROJECT, configure, verify_services

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ARTIFACTS = ROOT / ".qa"
BASE = ["accounts", "properties", "qa.test_environment"]
WORKFLOW = "properties.workflow_integration.WorkflowIntegrationTests"
MATCH_API = "properties.test_discovery.MatchApiTests"
PREFERENCES_API = "properties.test_discovery.BuyerPreferencesApiTests"
FIRESTORE = "properties.test_firestore.FirestoreDecisionTests"
SELECTION = "properties.test_selection.SelectionIntegrationTests"
BROWSER = "properties.workflow_e2e.WorkflowBrowserTests"
SELECTION_BROWSER = "properties.selection_e2e.SelectionBrowserTests"
STORIES = {
    "5.8": ([MATCH_API], [FIRESTORE, WORKFLOW + ".test_publication_azurite_photos_survive_confirmed_match",
                         WORKFLOW + ".test_failed_firestore_publication_compensates_real_blobs"],
            [BROWSER + ".test_interest_confirmation_and_rejection"]),
    "5.9": ([MATCH_API], ["properties.test_firestore.FirebaseFlowTests",
                         WORKFLOW + ".test_publication_azurite_photos_survive_confirmed_match"],
            [BROWSER + ".test_interest_confirmation_and_rejection"]),
    "8.6": ([PREFERENCES_API], [FIRESTORE + ".test_buyer_preferences_filter_isolation_reset_and_failed_write_are_persistent",
                               WORKFLOW + ".test_preferences_invalidate_cursor_and_survive_new_auth_session"],
            [BROWSER + ".test_preferences_profile_explorer_and_private_reset"]),
    "9.7": ([], [SELECTION, WORKFLOW + ".test_pending_proposal_on_another_home_stays_private_after_acceptance"],
            [BROWSER + ".test_two_homes_keep_independent_proposal_status"]),
    "9.8": ([], [SELECTION], [SELECTION_BROWSER]),
}


def port_open(port):
    try:
        with socket.create_connection((HOST, port), timeout=0.5):
            return True
    except OSError:
        return False


def wait_ports(ports, process, log):
    until = time.monotonic() + 60
    while time.monotonic() < until and process.poll() is None:
        if all(port_open(port) for port in ports):
            return
        time.sleep(0.3)
    raise RuntimeError(f"Los puertos {ports} no quedaron disponibles. Consulta {log}.")


def start_service(stack, command, name, cwd, ports):
    log = ARTIFACTS / f"{name}-{time.time_ns()}.log"
    stream = stack.enter_context(log.open("wb"))
    process = subprocess.Popen(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def stop_owned():
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                process.terminate()
            process.wait(timeout=10)

    stack.callback(stop_owned)
    wait_ports(ports, process, log)


def service_command(prefix, args):
    if os.name == "nt" and prefix[0].endswith(".cmd"):
        return ["cmd.exe", "/d", "/c", *prefix, *args]
    return [*prefix, *args]


def prepare_services(stack, *, prepare_container=False):
    active = {port: port_open(port) for port in (9099, 8080, 10000)}
    for port, already_running in active.items():
        if already_running:
            print(f"Reutilizando servicio en {HOST}:{port}.", flush=True)
    firebase = [name for port, name in ((9099, "auth"), (8080, "firestore")) if not active[port]]
    if firebase:
        configured_cli = os.environ.get("SWIPEHOME_FIREBASE_CLI")
        cli = ["node", configured_cli] if configured_cli else [
            "npx.cmd" if os.name == "nt" else "npx", "--yes", "--package", "firebase-tools@15.34.1", "firebase",
        ]
        start_service(stack, service_command(cli, [
            "emulators:start", "--project", PROJECT, "--only", ",".join(firebase),
            "--config", "tests/firebase.json",
        ]), "firebase", BACKEND, [port for port in (9099, 8080) if not active[port]])
    if not active[10000]:
        azurite = shutil.which("azurite-blob.cmd" if os.name == "nt" else "azurite-blob")
        if not azurite:
            raise RuntimeError("Instala Azurite o inicia su servicio Blob en el puerto 10000.")
        location = stack.enter_context(TemporaryDirectory(prefix="swipehome-azurite-"))
        start_service(stack, service_command([azurite], [
            "--blobHost", HOST, "--blobPort", "10000", "--location", location, "--silent",
        ]), "azurite", ROOT, [10000])
    verify_services(create_container=prepare_container or not active[10000])


def configure_browser():
    current = os.environ.get("SWIPEHOME_E2E_CHROME")
    if current:
        if Path(current).is_file():
            return
        raise RuntimeError("SWIPEHOME_E2E_CHROME no apunta al ejecutable del navegador.")
    for path in (
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
    ):
        if path.is_file():
            os.environ["SWIPEHOME_E2E_CHROME"] = str(path)
            return
    raise RuntimeError("Define SWIPEHOME_E2E_CHROME con la ruta a Chrome, Chromium o Edge.")


def run(command, cwd):
    subprocess.run(command, cwd=cwd, check=True)


def django(labels, *options):
    run([sys.executable, "-B", "manage.py", "test", *labels, *options, "--verbosity", "2"], BACKEND)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("all", "unit", "components", "integration", "e2e", "prepare", "services"),
                        default="all")
    parser.add_argument("--story", choices=STORIES)
    parser.add_argument("--test")
    parser.add_argument("--visual", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if args.test and (args.story or args.suite not in {"components", "integration", "e2e"}):
        parser.error("--test requiere components, integration o e2e y se usa sin --story.")
    if args.story and args.suite in {"prepare", "services", "unit"}:
        parser.error("--story se usa con all, components, integration o e2e.")
    if args.visual and args.suite not in {"all", "components", "e2e"}:
        parser.error("--visual requiere un recorrido en navegador.")

    configure()
    ARTIFACTS.mkdir(exist_ok=True)
    os.environ.update(
        PYTHONUTF8="1", SWIPEHOME_QA_ARTIFACTS=str(ARTIFACTS),
        SWIPEHOME_QA_VISUAL="1" if args.visual else "0", SWIPEHOME_QA_DEBUG="1" if args.debug else "0",
        CI="true", FIREBASE_CLI_DISABLE_UPDATE_CHECK="true",
    )
    focused = STORIES.get(args.story)
    if args.suite in {"all", "components", "e2e"}:
        configure_browser()
    with ExitStack() as services:
        if args.suite in {"all", "components", "e2e"}:
            os.environ["SWIPEHOME_QA_VITE_CACHE"] = services.enter_context(TemporaryDirectory(prefix="swipehome-vite-"))
        if args.suite in {"all", "integration", "e2e", "prepare", "services"}:
            prepare_services(services, prepare_container=args.suite == "prepare")
        if args.suite == "services":
            print("Servicios disponibles. Ctrl+C cierra únicamente los procesos que inició este comando.", flush=True)
            while True:
                time.sleep(0.5)
        if args.suite == "prepare":
            return
        if args.suite in {"unit", "all"}:
            if not focused:
                run(["node", "--test", "tests/*.test.mjs"], FRONTEND)
            labels = focused[0] if focused else BASE
            if labels:
                django(labels, "--exclude-tag", "integration")
            else:
                print(f"US {args.story}: la cobertura automatizada está en componentes, integración y E2E.", flush=True)
        if args.suite in {"components", "all"}:
            pattern = args.test or (f"US {re.escape(args.story)}" if args.story else None)
            options = [f"--test-name-pattern={pattern}"] if pattern else []
            run(["node", "--test", *options, "component/flows.spec.mjs"], FRONTEND)
        if args.suite in {"integration", "all"}:
            labels = [args.test] if args.test else focused[1] if focused else [*BASE, WORKFLOW]
            django(labels, "--tag", "integration")
        if args.suite in {"e2e", "all"}:
            labels = [args.test] if args.test else focused[2] if focused else [BROWSER, SELECTION_BROWSER]
            django(labels)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
    except (RuntimeError, OSError) as error:
        print(f"QA: {error}", file=sys.stderr)
        sys.exit(1)
