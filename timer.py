
from rich import print
from rich.console import RenderGroup
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.progress import Progress
from rich.console import Console
import time
from pynput import keyboard
import sqlite3
from win10toast import ToastNotifier
import argparse
import threading
import pywintypes

"""
- Class depenedencies
    - DB -> Session
    - UI -> (Session, DB)
"""


# These are global hotkeys
# Change this mapping according tou your taste.
KEY_MAPPING = {
    'pause/resume'     : '<ctrl>+<alt>+0',
    'distract'  : '<ctrl>+<alt>+9',
    'quit'      : '<ctrl>+<alt>+1'
}


class Session:
    def __init__(self, objective: str, duration_s: int):
        self.objective = objective
        self.duration_s = duration_s

        self.start_ts = int(time.time())        
        # short distractions, time stamps
        self.distraction_log = []
        # list of tuples, (start_ts, end_ts) 
        self.pauses = []
        
        # end time will be assigned when timer expires or stop button is hit.
        self.end_ts = None

        self.current_pause_start_ts = None

    def end(self) -> bool:
        if self.end_ts:
            return False
        
        self.end_ts = int(time.time())
        return True

    def register_distraction(self) -> bool:
        if self.current_pause_start_ts:
            return False
        
        self.distraction_log.append(int(time.time()))
        return True

    def start_pause(self) -> bool:
        # if session is already paused or ended, return false
        if self.current_pause_start_ts or self.end_ts:
            return False
        
        self.current_pause_start_ts = int(time.time())
        return True
    
    def end_pause(self) -> bool:
        # if session is not in a pause, return false
        if not self.current_pause_start_ts:
            return False

        self.pauses.append(
            (self.current_pause_start_ts,int(time.time()))
        )
        
        self.current_pause_start_ts = None
        return True
        
    def print_all(self):
        print(self.objective)
        print(self.distraction_log)
        print(self.pauses)
        print(self.start_ts)
        print(self.end_ts)


class DB:
    def __init__(self,path:str):
        self.conn = sqlite3.connect(path)
        self.cursor = self.conn.cursor()

    def write_session(self,session: Session) -> None:
        self.cursor.execute("select max(t_id) from tasks")
        count = self.cursor.fetchone()[0]
        max_t_id = count if count else 0

        self.cursor.execute(
            "insert into tasks(t_objective, t_duration_s, t_start_ts, t_end_ts) values(?,?,?,?)",
            [
                session.objective,
                session.duration_s,
                session.start_ts,
                session.end_ts
            ]
        )

        for ts in session.distraction_log:
            self.cursor.execute(
                "insert into distractions(t_id,d_ts) values(?,?)",
                [ max_t_id+1, ts ]
            )

        for s_ts, e_ts in session.pauses:
            self.cursor.execute(
                "insert into pauses(t_id,p_start_ts,p_end_ts) values(?,?,?)",
                [max_t_id+1, s_ts, e_ts]
            )

        self.conn.commit()

    def __del__(self):
        self.conn.commit()
        self.conn.close()


class UI:
    def __init__(self, db: DB):
        self.notifier = ToastNotifier()
        self.db = db
        self.console = Console()
        self.listener = keyboard.GlobalHotKeys({
            KEY_MAPPING['pause/resume']    : self.on_pause_key,
            KEY_MAPPING['distract']        : self.on_distract_key,
            KEY_MAPPING['quit']            : self.on_quit_key
        })
        self.listener.start()
        self.progess_bars = Progress(speed_estimate_period=5)
        

        self.key_pressed = None
        self.current_task_id = None
        self.objective : str = None
        self.duration_m : int= None
        self.current_session : Session = None
        
        self.is_paused = False
        self.end_task = False

    def nofity(self,msg:str) -> None:
        # Non blocking notify
        def _n(notifier : ToastNotifier, msg: str):
            try:
                notifier.show_toast(title="DeepWork Timer", msg=msg, duration=5,)
            except:
                pass            
            while notifier.notification_active():
                time.sleep(0.1)

        threading.Thread(target=_n,args=(self.notifier,msg)).start()

    def on_pause_key(self):
        # if no session is initilized, pause will not work
        if not self.current_session:
            return

        # If already paused then resume
        if self.is_paused:
            self.console.clear()
            self.console.print(Panel(f"[white]{self.objective}", style="green", title="Task Started"))
            self.progess_bars.start()
            self.current_session.end_pause()
            self.is_paused = False
            self.nofity("Task Resumed.")
        else:
            self.console.clear()
            self.console.print(Panel(f"[white]{self.objective}",style="red", title="Task Paused"))
            self.progess_bars.stop()
            self.is_paused = True
            self.current_session.start_pause()
            self.nofity("Task Paused")

    def on_distract_key(self):
        if not self.current_session or self.is_paused:
            return

        self.current_session.register_distraction()
        self.nofity("Distraction registerd.")
        
    def on_quit_key(self):
        self.end_task = True
        self.nofity("Task aborted.")

    def setup_event_loop(self) -> bool:
        wantRedo = False
        if self.objective:
            wantRedo = Confirm.ask("Redo previous task?")

        if not wantRedo:
            wantNewTask = Confirm.ask("Add new task?")
            if not wantNewTask:
                return False

            self.objective = Prompt.ask("[green]Objective") 

        self.duration_m = IntPrompt.ask("[blue]Duration (minutes)")
        
        if not self.current_task_id is None:
            self.progess_bars.remove_task(self.current_task_id)

        self.current_task_id = self.progess_bars.add_task(self.objective ,total=self.duration_m*60)
        self.console.log(self.current_task_id)
        self.progess_bars.start()
        self.console.clear()

        self.current_session = Session(self.objective, self.duration_m*60)

        return True

    def teardown_event_loop(self):
        self.progess_bars.stop()
        self.current_session.end()
        self.db.write_session(self.current_session)
        if self.progess_bars.finished:
            self.nofity("Task Finished")

    def main(self):
        while self.setup_event_loop():
            self.console.print(Panel(f"[white]{self.objective}", style="green", title="Task Started"))

            while not self.end_task:
                if self.is_paused:
                    time.sleep(0.1)
                    continue
                if not self.progess_bars.finished:
                    time.sleep(1)
                    self.progess_bars.update(self.current_task_id,advance=1)
                else:
                    self.end_task = True
                    continue


            self.teardown_event_loop()
            


def test_session() -> Session:
    session = Session("Testing...",300)
    session.register_distraction()
    time.sleep(1)
    session.start_pause()
    time.sleep(3)
    session.start_pause()
    session.end_pause()
    session.start_pause()
    session.end_pause()
    session.end()    
    session.print_all()

    return session

def test_db():
    db = DB("./dwtimer.db")
    session = test_session()
    db.write_session(session)

def init_db():
    conn = sqlite3.connect("dwtimer.db")
    conn.cursor().executescript(open("init.sql","r").read())


if( __name__ == "__main__" ):
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", help="Create schema in dwtimer.db file.", action="store_true")
    args = parser.parse_args()
    if args.i:
        try:
            init_db()
        except sqlite3.OperationalError:
            print("DB schema already created.")

    else:
        db = DB("dwtimer.db")
        UI(db).main()
        

