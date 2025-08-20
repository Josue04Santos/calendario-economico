import os
import sys
import subprocess
import threading
import time as t_sleep
import logging
from datetime import datetime, time, timedelta
from pathlib import Path
import json
import ctypes # <-- NOVA IMPORTAÇÃO para verificação de admin

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
# (Nenhuma mudança nesta seção)
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
    TASK_NAME = "AtualizarCalendarioInvesting"
    TIMEZONE = pytz.timezone('America/Sao_Paulo')
    
    if getattr(sys, 'frozen', False):
        BASE_DIR = Path(sys._MEIPASS)
    else:
        BASE_DIR = Path(__file__).parent

    DATA_DIR = Path(os.getenv("USERPROFILE")) / "Profit" / "Calendar"
    CSV_FILE = DATA_DIR / "calendario_profit_filtrado.csv"
    EXE_DESTINATION = DATA_DIR / "calendario_investing.exe"
    
    IMAGE_DIR = BASE_DIR / "image"
    SOUND_DIR = BASE_DIR / "sound"
    SETTINGS_FILE = DATA_DIR / "settings.json"
    
    IMPORTANCE_STARS = {"High": "★★★", "Medium": "★★", "Low": "★"}
    COLOR_MAP = {"High": "danger", "Medium": "warning", "Low": "info"}
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(exist_ok=True)
    SOUND_DIR.mkdir(exist_ok=True)

# ================== 2. CLASSES DE LÓGICA ==================
# (Nenhuma mudança nesta seção)

class CalendarManager:
    def __init__(self, config):
        self.config = config
        self.translator = Translator()

    def translate_text(self, text, dest_language='pt'):
        if not text or pd.isna(text):
            return ""
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
    def __init__(self, config, app_instance):
        self.config = config
        self.app = app_instance
        self.active = threading.Event()
        self.dispatched_alerts = set()
        pygame.mixer.init()

    def start(self):
        if self.active.is_set():
            logging.warning("Serviço de alerta já está ativo.")
            return
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
        if not sound_file_name:
            logging.warning("Nenhum som de alerta selecionado.")
            return
            
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
        if not self.config.CSV_FILE.exists():
            return

        try:
            df = pd.read_csv(self.config.CSV_FILE)
        except Exception as e:
            logging.error(f"Erro ao ler arquivo CSV para alertas: {e}")
            return

        now = datetime.now(self.config.TIMEZONE)
        alerts_to_show = []

        for _, row in df.iterrows():
            alert_key = f"{row['Data']} {row['Hora']} {row['Evento']}"
            if alert_key in self.dispatched_alerts:
                continue

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


class TaskScheduler:
    def __init__(self, task_name, exe_path):
        self.task_name = task_name
        self.exe_path = f'"{exe_path}"'

    def create_on_logon_task(self):
        query_cmd = ['schtasks', '/Query', '/TN', self.task_name]
        result = subprocess.run(query_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            logging.info(f"Tarefa '{self.task_name}' já existe.")
            return

        logging.info(f"Criando tarefa agendada '{self.task_name}'...")
        create_cmd = [
            'schtasks', '/Create', '/SC', 'ONLOGON', '/RL', 'HIGHEST',
            '/TN', self.task_name, '/TR', self.exe_path, '/F'
        ]
        try:
            subprocess.run(create_cmd, check=True, capture_output=True, text=True)
            logging.info("Tarefa agendada criada com sucesso.")
        except subprocess.CalledProcessError as e:
            logging.error(f"Falha ao criar tarefa agendada: {e.stderr}")

    def delete_task(self):
        logging.info(f"Deletando tarefa agendada '{self.task_name}'...")
        delete_cmd = ['schtasks', '/Delete', '/TN', self.task_name, '/F']
        try:
            subprocess.run(delete_cmd, check=True, capture_output=True, text=True)
            logging.info("Tarefa agendada deletada com sucesso.")
        except subprocess.CalledProcessError as e:
            if "não foi possível encontrar" in e.stderr.lower():
                 logging.warning(f"Tarefa '{self.task_name}' não encontrada.")
            else:
                logging.error(f"Falha ao deletar tarefa agendada: {e.stderr}")


# ================== 3. INTERFACE GRÁFICA (UI) ==================

class App(ttk.Window):
    def __init__(self, config):
        super().__init__(themename="litera", title=config.APP_NAME, size=(640, 480), resizable=(False, False))
        self.config = config
        self.withdraw()
        
        self.calendar_manager = CalendarManager(config)
        self.alert_service = AlertService(config, self) 
        self.scheduler = TaskScheduler(config.TASK_NAME, sys.executable)
        self.active_popups = []
        
        self.settings = self.load_settings()

        self._setup_ui()
        self._check_existing_csv()
        
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.center_window()
        self.deiconify()

    def load_settings(self):
        try:
            if self.config.SETTINGS_FILE.exists():
                with open(self.config.SETTINGS_FILE, 'r') as f:
                    return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logging.error(f"Erro ao carregar settings.json: {e}")
        return {"selected_sound": "medium.mp3"}

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
        self.icon_path = self.config.IMAGE_DIR / "AJJ_ComCor.ico"
        if self.icon_path.exists():
            self.iconbitmap(self.icon_path)

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
            "Low": ttk.BooleanVar(value=True), "Medium": ttk.BooleanVar(value=True), "High": ttk.BooleanVar(value=True)
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
        self.h_inicio.set("08"); self.m_inicio.set("45")
        
        end_frame = ttk.Frame(time_frame)
        end_frame.grid(row=0, column=1, sticky="e")
        ttk.Label(end_frame, text="Fim:").pack(side=LEFT, padx=(0, 5))
        self.h_fim = ttk.Spinbox(end_frame, from_=0, to=23, width=4, format="%02.0f"); self.h_fim.pack(side=LEFT)
        self.m_fim = ttk.Spinbox(end_frame, from_=0, to=59, width=4, format="%02.0f"); self.m_fim.pack(side=LEFT, padx=(5,0))
        self.h_fim.set("17"); self.m_fim.set("45")

        sound_frame = ttk.Labelframe(config_frame, text="Som do Alerta", padding=10)
        sound_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        sound_files = [f.name for f in self.config.SOUND_DIR.glob("*.mp3")]
        self.sound_var = ttk.StringVar(value=self.settings.get("selected_sound"))
        self.sound_selector = ttk.Combobox(sound_frame, textvariable=self.sound_var, values=sound_files, state="readonly")
        self.sound_selector.pack(fill=X, expand=YES)
        self.sound_selector.bind("<<ComboboxSelected>>", self.on_sound_select)

        self.exec_button = ttk.Button(config_frame, text="Executar e Monitorar", command=self.run_and_monitor, bootstyle="success")
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
        social_frame = ttk.Frame(qr_frame); social_frame.pack(pady=15)
        self._create_social_button(social_frame, "linkedin.png", "https://www.linkedin.com/in/josue-p-santos" ).pack(side=LEFT, padx=10)
        self._create_social_button(social_frame, "instagram.png", "https://www.instagram.com/josuepsantos" ).pack(side=RIGHT, padx=10)
        logo_path = self.config.IMAGE_DIR / "AJJ_LogoColorido.png"
        if logo_path.exists():
            try:
                logo_img = Image.open(logo_path).resize((150, 120), Image.Resampling.LANCZOS)
                self.logo_photo = ImageTk.PhotoImage(logo_img)
                ttk.Label(qr_frame, image=self.logo_photo).pack(pady=(10, 0))
            except Exception as e:
                logging.error(f"Erro ao carregar logo: {e}")
        ttk.Label(qr_frame, text="Desenvolvido por Josue Santos", font="-size 8 -slant italic").pack(pady=(5, 10))

    def on_sound_select(self, event=None):
        selected_sound = self.sound_var.get()
        self.settings["selected_sound"] = selected_sound
        self.save_settings()
        logging.info(f"Som do alerta alterado para: {selected_sound}")
        self.alert_service.play_sound()

    def test_notification(self):
        logging.info("Disparando notificação de teste.")
        test_data = {
            "evento": "Folha de Pagamento (Não-Agrícola)", "moeda": "USD",
            "hora": datetime.now().strftime("%H:%M"), "importancia": "High"
        }
        self.alert_service.play_sound()
        self.show_alert_popup(test_data)

    def _create_social_button(self, parent, image_name, url):
        path = self.config.IMAGE_DIR / image_name
        if not path.exists(): return ttk.Frame(parent)
        icon_img = Image.open(path).resize((32, 32), Image.Resampling.LANCZOS)
        icon_photo = ImageTk.PhotoImage(icon_img)
        button = ttk.Button(parent, image=icon_photo, bootstyle="link", command=lambda: webbrowser.open(url))
        button.image = icon_photo
        return button

    # --- CORREÇÃO 2: Apenas exibe o status, não inicia o monitoramento ---
    def _check_existing_csv(self):
        """Apenas verifica e exibe a data do último CSV, sem iniciar alertas."""
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
        self.exec_button.config(state=DISABLED)
        self.status_label.config(text="Baixando e traduzindo dados...", bootstyle="info")
        self.update_idletasks()
        importances = [key.lower() for key, var in self.vars.items() if var.get()]
        try:
            start_time = time(int(self.h_inicio.get()), int(self.m_inicio.get()))
            end_time = time(int(self.h_fim.get()), int(self.m_fim.get()))
        except ValueError:
            ttk.dialogs.Messagebox.show_error("Horário inválido! Use o formato HH e MM.", "Erro de Formato")
            self.exec_button.config(state=NORMAL)
            return
        threading.Thread(target=self._run_and_monitor_task, args=(importances, start_time, end_time), daemon=True).start()

    def _run_and_monitor_task(self, importances, start_time, end_time):
        success, message = self.calendar_manager.download_calendar(importances, start_time, end_time)
        self.after(0, self._update_ui_after_download, success, message)

    # --- CORREÇÃO 2: Inicia o serviço de alerta SOMENTE AQUI ---
    def _update_ui_after_download(self, success, message):
        """Atualiza a UI e inicia o monitoramento somente após o download."""
        if success:
            # Mostra mensagem de sucesso e cria a tarefa agendada
            ttk.dialogs.Messagebox.show_info(message, "Sucesso")
            self.scheduler.create_on_logon_task()
            
            # Inicia o serviço de alertas e esconde a janela principal
            self.alert_service.start()
            self.status_label.config(text="Monitoramento ativo. A janela pode ser fechada.")
            self.withdraw()
        else:
            # Mostra o erro e atualiza o status
            ttk.dialogs.Messagebox.show_error(message, "Falha no Download")
            self.status_label.config(text="Falha ao baixar. Verifique o log.", bootstyle="danger")
        
        # Reabilita o botão de execução em qualquer caso
        self.exec_button.config(state=NORMAL)

    def show_alert_popup(self, alert_data):
        popup = ttk.Toplevel(title="Alerta de Evento Econômico", size=(380, 220))
        popup.resizable(False, False)
        
        if self.icon_path.exists():
            popup.iconbitmap(self.icon_path)
        
        importancia = alert_data.get('importancia', 'Low')
        bootstyle_color = self.config.COLOR_MAP.get(importancia, "secondary")
        
        stars = self.config.IMPORTANCE_STARS.get(importancia, '★')
        
        header_frame = ttk.Frame(popup, bootstyle=bootstyle_color, height=60)
        header_frame.pack(fill=X, side=TOP)
        
        bell_icon = ttk.Label(header_frame, text="🔔", font=("Segoe UI Emoji", 24), bootstyle=f"{bootstyle_color}-inverse")
        bell_icon.pack(side=LEFT, padx=15, pady=10)
        
        header_text = f"Importância: {importancia} {stars}"
        event_title = ttk.Label(
            header_frame, 
            text=header_text, 
            font="-size 14 -weight bold", 
            bootstyle=f"{bootstyle_color}-inverse"
        )
        event_title.pack(side=LEFT, pady=10, fill=X, expand=YES)

        body_frame = ttk.Frame(popup, padding=15)
        body_frame.pack(fill=BOTH, expand=YES)
        body_frame.columnconfigure(1, weight=1)

        details = {
            "Moeda:": alert_data.get('moeda', 'N/A'),
            "Hora:": alert_data.get('hora', 'N/A'),
            "Evento:": alert_data.get('evento', 'N/A'),
        }

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
        screen_width, screen_height, gap, y_offset = self.winfo_screenwidth(), self.winfo_screenheight(), 10, 50
        for popup in reversed(self.active_popups[:]):
            if popup.winfo_exists():
                width, height = 380, 220 
                x = screen_width - width - 10
                y = screen_height - height - y_offset
                popup.geometry(f"{width}x{height}+{x}+{y}")
                y_offset += height + gap

    def uninstall(self):
        answer = ttk.dialogs.Messagebox.show_question("Tem certeza que deseja desinstalar?", "Confirmar Desinstalação")
        if answer != "Yes": return
        logging.info("Iniciando processo de desinstalação...")
        self.alert_service.stop()
        self.scheduler.delete_task()
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
        """Ação ao fechar a janela principal."""
        # Se o serviço de alerta estiver ativo, apenas escondemos a janela
        if self.alert_service.active.is_set() and not force:
            self.withdraw()
            ttk.dialogs.Messagebox.show_info(
                "O aplicativo continua monitorando em segundo plano.", 
                "Monitoramento Ativo"
            )
        else:
            # Se não estiver monitorando, ou se for forçado, encerra tudo
            self.alert_service.stop()
            self.quit()
            self.destroy()

    def center_window(self):
        """Centraliza a janela na tela."""
        self.update_idletasks()
        width, height = self.winfo_width(), self.winfo_height()
        x, y = (self.winfo_screenwidth() // 2) - (width // 2), (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')

# ================== 4. PONTO DE ENTRADA ==================

def is_admin():
    """Verifica se o script está rodando com privilégios de administrador."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

# O ponto de entrada fica mais simples:
if __name__ == "__main__":
    # A verificação de admin não é mais necessária aqui, pois o .exe já força isso.
    logging.info("Aplicação iniciada.")

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

