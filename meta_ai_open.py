# ComfyUI_MetaAi/meta_ai_open.py
import os
import time
import psutil
import threading
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

class MetaAiBrowserNode:
    def __init__(self):
        self.active = True
        self.browser_thread = None
        self.browser_running = False

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "activate": ("BOOLEAN", {"default": True}),
                "profile_name": ("STRING", {"default": "meta_playwright_profile3"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("profile_path",)
    FUNCTION = "launch_browser"
    CATEGORY = "MetaAI"

    def launch_browser(self, activate, profile_name="meta_playwright_profile3"):
        if not activate:
            return (f"Browser deactivated by switch",)
        
        # Aseguramos que el nombre del perfil no esté vacío
        profile_name = profile_name.strip() or "meta_playwright_profile3"
        
        # Directorio fijo para el perfil
        user_data_dir = Path(__file__).parent / profile_name
        user_data_dir.mkdir(parents=True, exist_ok=True)

        # Iniciar el navegador en un hilo separado
        if not self.browser_running:
            self.browser_thread = threading.Thread(
                target=self._run_browser, 
                args=(str(user_data_dir),)
            )
            self.browser_thread.daemon = True
            self.browser_thread.start()
            self.browser_running = True

        return (str(user_data_dir.resolve()).replace("\\", "/"),)

    def _run_browser(self, user_data_dir):
        """
        Función que encapsula la lógica de apertura del navegador con Playwright.
        """
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=False, # Siempre False para que el usuario pueda interactuar
                    args=[
                        "--start-fullscreen", # O "--start-maximized" si fullscreen no es deseado
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=TranslateUI",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                    viewport=None, # Permite usar toda la pantalla
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                )

                page = context.pages[0] if context.pages else context.new_page()
                print("Navegando a Meta AI...")
                page.goto("https://www.meta.ai/media", timeout=60000)
                print("Pagina de Meta AI cargada. Cierra la ventana manualmente para salir.")

                # === Obtener PID de Chrome ===
                try:
                    # Intenta obtener el PID directamente desde el contexto de Playwright
                    pid = context._impl_obj._browser_process.pid
                except Exception:
                    # Si falla, intenta encontrarlo usando psutil
                    current_pid = os.getpid()
                    parent = psutil.Process(current_pid)
                    children = parent.children(recursive=True)
                    chrome_procs = [c for c in children if 'chrome' in c.name().lower()]
                    pid = chrome_procs[-1].pid if chrome_procs else None

                if pid is None:
                    print("No se pudo obtener el PID de Chrome.")
                    context.close()
                    self.browser_running = False
                    return

                # === Mantener el hilo vivo mientras Chrome esté abierto ===
                def is_chrome_running():
                    try:
                        # Verifica si el proceso con el PID existe y está corriendo
                        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
                    except psutil.NoSuchProcess:
                        # Si el proceso no existe, asume que no está corriendo
                        return False

                print(f"Monitoreando el proceso de Chrome (PID: {pid})...")
                while is_chrome_running():
                    # Espera un breve periodo antes de verificar nuevamente
                    time.sleep(0.5)

                print("Ventana de Chrome cerrada. Finalizando script.")
                # El navegador ya debería estar cerrado, pero asegurémonos
                try:
                    context.close()
                except:
                    pass # Puede que ya esté cerrado

        except Exception as e:
            # Imprimir el mensaje de error sin emojis en stderr
            print(f"Error al abrir Meta AI: {e}", file=sys.stderr)
        
        self.browser_running = False