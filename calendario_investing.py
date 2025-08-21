import os
import sys
import subprocess
import threading
import time as t_sleep
import logging
from datetime import datetime, time, timedelta
from pathlib import Path
import json
import ctypes

import pandas as pd
import psutil
import pytz
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from PIL import Image, ImageTk
import webbrowser
import pygame
from googletrans import Translator

# ================== 1. CONFIGURAÇÃO E INICIALIZAÇÃO ==================
log_dir = Path.home() / "AppData" / "Local" / "CalendarApp"
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "app.log"),
        logging.StreamHandler()
    ]
)

def kill_previous_instances():
    # (Código inalterado)
    current_pid = os.getpid()
    try:
        current_exe = psutil.Process(current_pid).exe()
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            if proc.info['exe'] == current_exe and proc.pid != current_pid:
                logging.warning(f"Encerrando processo antigo: PID {proc.pid}")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except psutil.TimeoutExpired:
                    proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
        logging.error(f"Erro ao tentar encerrar processos antigos: {e}")

kill_previous_instances()


class Config:
    APP_NAME = "Calendário Econômico"
    # --- MUDANÇA: Nomes base para as tarefas ---
    TASK_NAME_LOGON = "AtualizarCalendario_Logon"
    TASK_NAME_DAILY = "AtualizarCalendario_Diario"
    TIMEZONE = pytz.timezone('America/Sao_Paulo')
    
    if getattr(sys, 'frozen', False):
        BASE_DIR = Path(sys._MEIPASS)
    else:
        BASE_DIR = Path(__file__).parent

    DATA_DIR = Path(os.getenv("USERPROFILE")) / "Profit" / "Calendar"
    CSV_FILE = DATA_DIR / "calendario_profit_filtrado.csv"
    EXE_DESTINATION = DATA_DIR / "CalendarioEconomico.exe"
    
    IMAGE_DIR = BASE_DIR / "image"
    SOUND_DIR = BASE_DIR / "sound"
    SETTINGS_FILE = DATA_DIR / "settings.json"
    
    IMPORTANCE_STARS = {"High": "★★★", "Medium": "★★", "Low": "★"}
    COLOR_MAP = {"High": "danger", "Medium": "warning", "Low": "info"}
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(exist_ok=True)
    SOUND_DIR.mkdir(exist_ok=True)

# ================== 2. CLASSES DE LÓGICA ==================

class CalendarManager:
    # (Código inalterado)
    def __init__(self, config):
        self.config = config
        self.translator = Translator()

    def translate_text(self, text, dest_language='pt'):
        if not text or pd.isna(text): return ""
        try:
            t_sleep.sleep(0.1) 
            return self.translator.translate(text, dest=dest_language).text
        except Exception as e:
            logging.error(f"Erro ao traduzir '{text}': {e}")
            return text

    def download_calendar(self, importances, start_time, end_time):
        try:
            import investpy
            logging.info("Baixando dados do calendário via investpy...")
            events = investpy.news.economic_calendar(countries=['united states', 'brazil'])
        except Exception as e:
            logging.error(f"Falha ao baixar calendário: {e}")
            return False, f"Erro ao baixar calendário: {e}"

        events['datetime'] = pd.to_datetime(events['date'] + ' ' + events['time'], dayfirst=True, errors='coerce')
        
        filtered_events = events[
            events["importance"].isin(importances) &
            (events['datetime'].dt.time >= start_time) &
            (events['datetime'].dt.time <= end_time)
        ].copy()

        if filtered_events.empty:
            msg = "Nenhum evento encontrado com os filtros selecionados."
            logging.warning(msg)
            return False, msg

        logging.info("Iniciando tradução dos nomes dos eventos...")
        filtered_events['event_pt'] = filtered_events['event'].fillna('').apply(self.translate_text)
        logging.info("Tradução concluída.")

        filtered_events['Data'] = filtered_events['datetime'].dt.strftime('%d/%m/%Y')
        filtered_events['Hora'] = filtered_events['datetime'].dt.strftime('%H:%M')
        filtered_events['Evento'] = filtered_events['event_pt'] 
        filtered_events['Moeda'] = filtered_events['currency']
        filtered_events['Importância'] = filtered_events['importance'].str.capitalize()
        filtered_events['Previsão'] = filtered_events['forecast']
        filtered_events['Anterior'] = filtered_events['previous']
        filtered_events['Real'] = filtered_events['actual']
        
        profit_columns = ['Data', 'Hora', 'Evento', 'Moeda', 'Importância', 'Previsão', 'Anterior', 'Real']
        
        try:
            filtered_events[profit_columns].to_csv(self.config.CSV_FILE, index=False, encoding="utf-8-sig")
            logging.info(f"Calendário salvo com sucesso em: {self.config.CSV_FILE}")
            return True, f"CSV atualizado com sucesso!"
        except IOError as e:
            msg = f"Falha ao salvar o arquivo CSV: {e}"
            logging.error(msg)
            return False, msg


class AlertService:
    # (Código inalterado)
    def __init__(self, config, app_instance):
        self.config = config
        self.app = app_instance
        self.active = threading.Event()
        self.dispatched_alerts = set()
        pygame.mixer.init()

    def start(self):
        if self.active.is_set(): return
        logging.info("Iniciando serviço de alertas.")
        self.active.set()
        threading.Thread(target=self._alert_loop, daemon=True).start()

    def stop(self):
        logging.info("Parando serviço de alertas.")
        self.active.clear()

    def _alert_loop(self):
        while self.active.is_set():
            self.check_events()
            t_sleep.sleep(15)

    def play_sound(self):
        sound_file_name = self.app.get_selected_sound()
        if not sound_file_name: return
        path = self.config.SOUND_DIR / sound_file_name
        if path.exists():
            try:
                pygame.mixer.music.load(path)
                pygame.mixer.music.play()
                logging.info(f"Tocando som de alerta: {sound_file_name}")
            except pygame.error as e:
                logging.error(f"Erro ao tocar som {path}: {e}")
        else:
            logging.error(f"Arquivo de som '{sound_file_name}' não encontrado.")

    def check_events(self):
        if not self.config.CSV_FILE.exists(): return
        try:
            df = pd.read_csv(self.config.CSV_FILE)
        except Exception as e:
            logging.error(f"Erro ao ler arquivo CSV para alertas: {e}")
            return
        now = datetime.now(self.config.TIMEZONE)
        alerts_to_show = []
        for _, row in df.iterrows():
            alert_key = f"{row['Data']} {row['Hora']} {row['Evento']}"
            if alert_key in self.dispatched_alerts: continue
            try:
                event_time_str = f"{row['Data']} {row['Hora']}"
                event_time = datetime.strptime(event_time_str, "%d/%m/%Y %H:%M")
                event_time = self.config.TIMEZONE.localize(event_time)
            except (ValueError, TypeError) as e:
                logging.error(f"Formato de data/hora inválido para o evento {row.get('Evento', 'N/A')}: {e}")
                continue
            alert_time_start = event_time - timedelta(minutes=5)
            if alert_time_start <= now < event_time:
                alerts_to_show.append({
                    "evento": row['Evento'], "moeda": row['Moeda'],
                    "hora": row['Hora'], "importancia": row['Importância'],
                    "key": alert_key
                })
        alerts_to_show.sort(key=lambda x: list(self.config.IMPORTANCE_STARS.keys()).index(x.get('importancia', 'Low')))
        for alert_data in alerts_to_show:
            self.play_sound()
            self.app.show_alert_popup(alert_data)
            self.dispatched_alerts.add(alert_data['key'])


# --- MUDANÇA: Classe TaskScheduler agora gerencia duas tarefas ---
class TaskScheduler:
    """Gerencia as tarefas agendadas no Windows."""
    def __init__(self, config, exe_path):
        self.config = config
        # Adiciona o argumento para que as tarefas rodem em modo silencioso
        self.exe_path_with_arg = f'"{exe_path}" --background-update'

    def _create_task(self, task_name, schedule_type, time=""):
        """Função genérica para criar uma tarefa."""
        query_cmd = ['schtasks', '/Query', '/TN', task_name]
        if subprocess.run(query_cmd, capture_output=True).returncode == 0:
            logging.info(f"Tarefa '{task_name}' já existe.")
            return

        logging.info(f"Criando tarefa agendada '{task_name}'...")
        create_cmd = [
            'schtasks', '/Create', '/RL', 'HIGHEST', '/F',
            '/TN', task_name,
            '/TR', self.exe_path_with_arg,
            '/SC', schedule_type
        ]
        if time:
            create_cmd.extend(['/ST', time])
        
        try:
            subprocess.run(create_cmd, check=True, capture_output=True, text=True)
            logging.info(f"Tarefa '{task_name}' criada com sucesso.")
        except subprocess.CalledProcessError as e:
            logging.error(f"Falha ao criar tarefa '{task_name}': {e.stderr}")

    def _delete_task(self, task_name):
        """Função genérica para deletar uma tarefa."""
        logging.info(f"Deletando tarefa agendada '{task_name}'...")
        delete_cmd = ['schtasks', '/Delete', '/TN', task_name, '/F']
        try:
            subprocess.run(delete_cmd, check=True, capture_output=True, text=True)
            logging.info(f"Tarefa '{task_name}' deletada com sucesso.")
        except subprocess.CalledProcessError as e:
            if "não foi possível encontrar" in e.stderr.lower():
                 logging.warning(f"Tarefa '{task_name}' não encontrada para deleção.")
            else:
                logging.error(f"Falha ao deletar tarefa '{task_name}': {e.stderr}")

    def create_all_tasks(self):
        """Cria ambas as tarefas de atualização."""
        self._create_task(self.config.TASK_NAME_LOGON, "ONLOGON")
        self._create_task(self.config.TASK_NAME_DAILY, "DAILY", "08:30")

    def delete_all_tasks(self):
        """Deleta ambas as tarefas de atualização."""
        self._delete_task(self.config.TASK_NAME_LOGON)
        self._delete_task(self.config.TASK_NAME_DAILY)


# ================== 3. INTERFACE GRÁFICA (UI) ==================

class App(ttk.Window):
    def __init__(self, config):
        super().__init__(themename="litera", title=config.APP_NAME, size=(640, 500), resizable=(False, False))
        self.config = config
        self.withdraw()
        
        self.calendar_manager = CalendarManager(config)
        self.alert_service = AlertService(config, self) 
        # --- MUDANÇA: Passa a classe Config para o scheduler ---
        self.scheduler = TaskScheduler(config, config.EXE_DESTINATION)
        self.active_popups = []
        
        self.settings = self.load_settings()

        self._setup_ui()
        self._check_existing_csv()
        
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.center_window()
        self.deiconify()

    # (load_settings, save_settings, get_selected_sound inalterados)
    def load_settings(self):
        try:
            if self.config.SETTINGS_FILE.exists():
                with open(self.config.SETTINGS_FILE, 'r') as f:
                    return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logging.error(f"Erro ao carregar settings.json: {e}")
        return {"selected_sound": "medium.mp3", "importances": ["low", "medium", "high"], "start_time": "08:45", "end_time": "17:45"}

    def save_settings(self):
        try:
            with open(self.config.SETTINGS_FILE, 'w') as f:
                json.dump(self.settings, f, indent=4)
            logging.info("Configurações salvas com sucesso.")
        except IOError as e:
            logging.error(f"Erro ao salvar settings.json: {e}")

    def get_selected_sound(self):
        return self.settings.get("selected_sound")

    def _setup_ui(self):
        # (Código da UI quase todo inalterado, apenas o tamanho da janela e a chamada ao scheduler)
        self.icon_path = self.config.IMAGE_DIR / "AJJ_ComCor.ico"
        if self.icon_path.exists(): self.iconbitmap(self.icon_path)
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=BOTH, expand=YES)
        config_frame = ttk.Frame(main_frame)
        config_frame.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 10))
        config_frame.columnconfigure(0, weight=1)
        config_frame.columnconfigure(1, weight=1)
        ttk.Label(config_frame, text="Configurações de Filtro", font="-size 12 -weight bold").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 15))
        imp_frame = ttk.Labelframe(config_frame, text="Importância", padding=10)
        imp_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        imp_frame.columnconfigure((0,1,2), weight=1)
        self.vars = {
            "Low": ttk.BooleanVar(value="low" in self.settings.get("importances", [])), 
            "Medium": ttk.BooleanVar(value="medium" in self.settings.get("importances", [])), 
            "High": ttk.BooleanVar(value="high" in self.settings.get("importances", []))
        }
        ttk.Checkbutton(imp_frame, text="Low (★)", variable=self.vars["Low"], bootstyle="primary").grid(row=0, column=0)
        ttk.Checkbutton(imp_frame, text="Medium (★★)", variable=self.vars["Medium"], bootstyle="primary").grid(row=0, column=1)
        ttk.Checkbutton(imp_frame, text="High (★★★)", variable=self.vars["High"], bootstyle="primary").grid(row=0, column=2)
        time_frame = ttk.Labelframe(config_frame, text="Horários (HH:MM)", padding=10)
        time_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        time_frame.columnconfigure((0,1), weight=1)
        start_frame = ttk.Frame(time_frame)
        start_frame.grid(row=0, column=0, sticky="w")
        ttk.Label(start_frame, text="Início:").pack(side=LEFT, padx=(0, 5))
        self.h_inicio = ttk.Spinbox(start_frame, from_=0, to=23, width=4, format="%02.0f"); self.h_inicio.pack(side=LEFT)
        self.m_inicio = ttk.Spinbox(start_frame, from_=0, to=59, width=4, format="%02.0f"); self.m_inicio.pack(side=LEFT, padx=(5,0))
        start_h, start_m = self.settings.get("start_time", "08:45").split(':')
        self.h_inicio.set(start_h); self.m_inicio.set(start_m)
        end_frame = ttk.Frame(time_frame)
        end_frame.grid(row=0, column=1, sticky="e")
        ttk.Label(end_frame, text="Fim:").pack(side=LEFT, padx=(0, 5))
        self.h_fim = ttk.Spinbox(end_frame, from_=0, to=23, width=4, format="%02.0f"); self.h_fim.pack(side=LEFT)
        self.m_fim = ttk.Spinbox(end_frame, from_=0, to=59, width=4, format="%02.0f"); self.m_fim.pack(side=LEFT, padx=(5,0))
        end_h, end_m = self.settings.get("end_time", "17:45").split(':')
        self.h_fim.set(end_h); self.m_fim.set(end_m)
        sound_frame = ttk.Labelframe(config_frame, text="Som do Alerta", padding=10)
        sound_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        sound_files = [f.name for f in self.config.SOUND_DIR.glob("*.mp3")]
        self.sound_var = ttk.StringVar(value=self.settings.get("selected_sound"))
        self.sound_selector = ttk.Combobox(sound_frame, textvariable=self.sound_var, values=sound_files, state="readonly")
        self.sound_selector.pack(fill=X, expand=YES)
        self.sound_selector.bind("<<ComboboxSelected>>", self.on_sound_select)
        self.exec_button = ttk.Button(config_frame, text="Salvar e Monitorar", command=self.run_and_monitor, bootstyle="success")
        self.exec_button.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 5), ipady=5)
        self.test_button = ttk.Button(config_frame, text="Testar Notificação", command=self.test_notification, bootstyle="info")
        self.test_button.grid(row=5, column=0, columnspan=2, sticky="ew", pady=5, ipady=5)
        self.uninstall_button = ttk.Button(config_frame, text="Desinstalar", command=self.uninstall, bootstyle="danger-outline")
        self.uninstall_button.grid(row=6, column=0, columnspan=2, sticky="ew", pady=5, ipady=5)
        self.status_label = ttk.Label(config_frame, text="Pronto para iniciar.", bootstyle="secondary")
        self.status_label.grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))
        qr_frame = ttk.Frame(main_frame, width=230)
        qr_frame.pack(side=RIGHT, fill=Y)
        qr_path = self.config.IMAGE_DIR / "QRcode.png"
        if qr_path.exists():
            qr_img = Image.open(qr_path).resize((150, 150), Image.Resampling.LANCZOS)
            self.qr_photo = ImageTk.PhotoImage(qr_img)
            ttk.Label(qr_frame, image=self.qr_photo).pack(pady=10)
        ttk.Label(qr_frame, text="Apoie o desenvolvedor!", font="-weight bold").pack()
        social_frame = ttk.Frame(qr_frame)
        social_frame.pack(pady=15)
        social_frame.columnconfigure((0, 1, 2), weight=1)
        self._create_social_button(social_frame, "linkedin.png", "https://www.linkedin.com/in/josue-p-santos" ).grid(row=0, column=0, padx=5)
        self._create_social_button(social_frame, "github.png", "https://github.com/Josue04Santos" ).grid(row=0, column=1, padx=5)
        self._create_social_button(social_frame, "instagram.png", "https://www.instagram.com/josuepsantos" ).grid(row=0, column=2, padx=5)
        logo_path = self.config.IMAGE_DIR / "AJJ_LogoColorido.png"
        if logo_path.exists():
            try:
                logo_img = Image.open(logo_path).resize((150, 75), Image.Resampling.LANCZOS)
                self.logo_photo = ImageTk.PhotoImage(logo_img)
                ttk.Label(qr_frame, image=self.logo_photo).pack(pady=(10, 0))
            except Exception as e:
                logging.error(f"Erro ao carregar logo: {e}")
        ttk.Label(qr_frame, text="Desenvolvido por Josue Santos", font="-size 8 -slant italic").pack(pady=(5, 10))

    def on_sound_select(self, event=None):
        # (Código inalterado)
        selected_sound = self.sound_var.get()
        self.settings["selected_sound"] = selected_sound
        self.save_settings()
        logging.info(f"Som do alerta alterado para: {selected_sound}")
        self.alert_service.play_sound()

    def test_notification(self):
        # (Código inalterado)
        logging.info("Disparando notificação de teste.")
        test_data = { "evento": "Folha de Pagamento (Não-Agrícola)", "moeda": "USD", "hora": datetime.now().strftime("%H:%M"), "importancia": "High" }
        self.alert_service.play_sound()
        self.show_alert_popup(test_data)

    def _create_social_button(self, parent, image_name, url):
        # (Código inalterado)
        path = self.config.IMAGE_DIR / image_name
        if not path.exists(): 
            logging.warning(f"Ícone social não encontrado: {image_name}")
            return ttk.Frame(parent)
        icon_img = Image.open(path).resize((32, 32), Image.Resampling.LANCZOS)
        icon_photo = ImageTk.PhotoImage(icon_img)
        button = ttk.Button(parent, image=icon_photo, bootstyle="link", command=lambda: webbrowser.open(url))
        button.image = icon_photo
        return button

    def _check_existing_csv(self):
        # (Código inalterado)
        if self.config.CSV_FILE.exists():
            try:
                last_mod_ts = os.path.getmtime(self.config.CSV_FILE)
                last_mod_dt = datetime.fromtimestamp(last_mod_ts)
                self.status_label.config(text=f"Última atualização: {last_mod_dt:%d/%m/%Y %H:%M}")
            except Exception as e:
                logging.error(f"Erro ao verificar CSV existente: {e}")
                self.status_label.config(text="Erro ao carregar CSV anterior.", bootstyle="danger")
        else:
            self.status_label.config(text="Nenhum calendário encontrado. Execute para baixar.")

    def run_and_monitor(self):
        # (Código inalterado, apenas a lógica de salvar as configurações)
        self.exec_button.config(state=DISABLED)
        self.status_label.config(text="Salvando e baixando dados...", bootstyle="info")
        self.update_idletasks()
        
        importances = [key.lower() for key, var in self.vars.items() if var.get()]
        start_time_str = f"{self.h_inicio.get()}:{self.m_inicio.get()}"
        end_time_str = f"{self.h_fim.get()}:{self.m_fim.get()}"
        
        self.settings["importances"] = importances
        self.settings["start_time"] = start_time_str
        self.settings["end_time"] = end_time_str
        self.save_settings()

        try:
            start_time = time(int(self.h_inicio.get()), int(self.m_inicio.get()))
            end_time = time(int(self.h_fim.get()), int(self.m_fim.get()))
        except ValueError:
            ttk.dialogs.Messagebox.show_error("Horário inválido!", "Erro de Formato")
            self.exec_button.config(state=NORMAL)
            return
            
        threading.Thread(target=self._run_and_monitor_task, args=(importances, start_time, end_time), daemon=True).start()

    def _run_and_monitor_task(self, importances, start_time, end_time):
        # (Código inalterado)
        success, message = self.calendar_manager.download_calendar(importances, start_time, end_time)
        self.after(0, self._update_ui_after_download, success, message)

    def _update_ui_after_download(self, success, message):
        # --- MUDANÇA: Chama create_all_tasks ---
        if success:
            ttk.dialogs.Messagebox.show_info(message, "Sucesso")
            self.scheduler.create_all_tasks() # Cria/atualiza AMBAS as tarefas
            self.alert_service.start()
            self.status_label.config(text="Monitoramento ativo. A janela pode ser fechada.")
            self.withdraw()
        else:
            ttk.dialogs.Messagebox.show_error(message, "Falha no Download")
            self.status_label.config(text="Falha ao baixar. Verifique o log.", bootstyle="danger")
        self.exec_button.config(state=NORMAL)

    def show_alert_popup(self, alert_data):
        # (Código inalterado)
        popup = ttk.Toplevel(title="Alerta de Evento Econômico", size=(380, 220))
        popup.resizable(False, False)
        if self.icon_path.exists(): popup.iconbitmap(self.icon_path)
        importancia = alert_data.get('importancia', 'Low')
        bootstyle_color = self.config.COLOR_MAP.get(importancia, "secondary")
        stars = self.config.IMPORTANCE_STARS.get(importancia, '★')
        header_frame = ttk.Frame(popup, bootstyle=bootstyle_color, height=60)
        header_frame.pack(fill=X, side=TOP)
        bell_icon = ttk.Label(header_frame, text="🔔", font=("Segoe UI Emoji", 24), bootstyle=f"{bootstyle_color}-inverse")
        bell_icon.pack(side=LEFT, padx=15, pady=10)
        header_text = f"Importância: {importancia} {stars}"
        event_title = ttk.Label(header_frame, text=header_text, font="-size 14 -weight bold", bootstyle=f"{bootstyle_color}-inverse")
        event_title.pack(side=LEFT, pady=10, fill=X, expand=YES)
        body_frame = ttk.Frame(popup, padding=15)
        body_frame.pack(fill=BOTH, expand=YES)
        body_frame.columnconfigure(1, weight=1)
        details = {"Moeda:": alert_data.get('moeda', 'N/A'), "Hora:": alert_data.get('hora', 'N/A'), "Evento:": alert_data.get('evento', 'N/A')}
        for i, (label, value) in enumerate(details.items()):
            ttk.Label(body_frame, text=label, font="-weight bold").grid(row=i, column=0, sticky="w", padx=(0, 10), pady=2)
            value_label = ttk.Label(body_frame, text=value, wraplength=220)
            value_label.grid(row=i, column=1, sticky="w", pady=2)
        footer_frame = ttk.Frame(popup, padding=(10, 15), bootstyle="light")
        footer_frame.pack(fill=X, side=BOTTOM)
        footer_frame.columnconfigure((0,1), weight=1)
        def close_popup():
            if popup.winfo_exists():
                if popup in self.active_popups: self.active_popups.remove(popup)
                popup.destroy()
                self._stack_popups()
        def open_csv_and_close():
            if self.config.CSV_FILE.exists(): os.startfile(self.config.CSV_FILE)
            close_popup()
        open_btn = ttk.Button(footer_frame, text="📄 Abrir CSV", command=open_csv_and_close, bootstyle="success")
        open_btn.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        close_btn = ttk.Button(footer_frame, text="❌ Fechar", command=close_popup, bootstyle="secondary-outline")
        close_btn.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        popup.attributes("-topmost", True)
        
        self.active_popups.append(popup)
        self._stack_popups()
        popup.after(30000, close_popup)

    def _stack_popups(self):
        # (Código inalterado)
        screen_width, screen_height, gap, y_offset = self.winfo_screenwidth(), self.winfo_screenheight(), 10, 50
        for popup in reversed(self.active_popups[:]):
            if popup.winfo_exists():
                width, height = 380, 220 
                x = screen_width - width - 10
                y = screen_height - height - y_offset
                popup.geometry(f"{width}x{height}+{x}+{y}")
                y_offset += height + gap

    def uninstall(self):
        # --- MUDANÇA: Chama delete_all_tasks ---
        answer = ttk.dialogs.Messagebox.show_question("Tem certeza que deseja desinstalar?", "Confirmar Desinstalação")
        if answer != "Yes": return
        logging.info("Iniciando processo de desinstalação...")
        self.alert_service.stop()
        self.scheduler.delete_all_tasks() # Deleta AMBAS as tarefas
        try:
            if self.config.CSV_FILE.exists(): self.config.CSV_FILE.unlink()
            if self.config.SETTINGS_FILE.exists(): self.config.SETTINGS_FILE.unlink()
            if self.config.EXE_DESTINATION.exists() and getattr(sys, 'frozen', False):
                 if sys.executable != str(self.config.EXE_DESTINATION): self.config.EXE_DESTINATION.unlink()
            for popup in self.active_popups[:]:
                if popup.winfo_exists(): popup.destroy()
            ttk.dialogs.Messagebox.show_info("Programa desinstalado com sucesso.", "Desinstalação Concluída")
            self._on_close(force=True)
        except Exception as e:
            logging.error(f"Erro durante a desinstalação: {e}")
            ttk.dialogs.Messagebox.show_error(f"Falha ao desinstalar: {e}", "Erro")

    def _on_close(self, force=False):
        # (Código inalterado)
        if self.alert_service.active.is_set() and not force:
            self.withdraw()
            ttk.dialogs.Messagebox.show_info(
                "O aplicativo continua monitorando em segundo plano.", 
                "Monitoramento Ativo"
            )
        else:
            self.alert_service.stop()
            self.quit()
            self.destroy()

    def center_window(self):
        # (Código inalterado)
        self.update_idletasks()
        width, height = self.winfo_width(), self.winfo_height()
        x, y = (self.winfo_screenwidth() // 2) - (width // 2), (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')

# ================== 4. PONTO DE ENTRADA ==================

# --- MUDANÇA: Nova função para rodar em modo silencioso ---
def run_background_update():
    """
    Executa apenas o download do CSV, sem interface gráfica.
    É chamado pelas tarefas agendadas.
    """
    logging.info("Executando em modo de atualização em background...")
    app_config = Config()
    
    # Carrega as últimas configurações salvas pelo usuário
    settings = {}
    try:
        if app_config.SETTINGS_FILE.exists():
            with open(app_config.SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
    except Exception as e:
        logging.error(f"Não foi possível carregar configurações para background update: {e}")

    # Usa as configurações salvas ou valores padrão
    importances = settings.get("importances", ["low", "medium", "high"])
    start_h, start_m = settings.get("start_time", "08:45").split(':')
    end_h, end_m = settings.get("end_time", "17:45").split(':')
    start_time = time(int(start_h), int(start_m))
    end_time = time(int(end_h), int(end_m))

    calendar_manager = CalendarManager(app_config)
    success, message = calendar_manager.download_calendar(importances, start_time, end_time)
    
    if success:
        logging.info(f"Atualização em background concluída: {message}")
    else:
        logging.error(f"Falha na atualização em background: {message}")
    
    # Encerra o processo após a tarefa
    sys.exit(0)


if __name__ == "__main__":
    # --- MUDANÇA: Verifica se deve rodar em modo background ou com UI ---
    if '--background-update' in sys.argv:
        run_background_update()
    else:
        # Se não, executa o programa normalmente com a interface gráfica
        logging.info("Aplicação iniciada com interface gráfica.")

        if getattr(sys, 'frozen', False):
            if Path(sys.executable) != Config.EXE_DESTINATION:
                import shutil
                try:
                    shutil.copy2(sys.executable, Config.EXE_DESTINATION)
                    logging.info(f"Executável copiado para {Config.EXE_DESTINATION}")
                except (IOError, shutil.Error) as e:
                    logging.error(f"Não foi possível copiar o executável: {e}")

        app_config = Config()
        app = App(app_config)
        app.mainloop()
        logging.info("Aplicação encerrada.")
