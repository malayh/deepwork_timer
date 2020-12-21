
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

"""
- Class depenedencies
    - DB -> Session
    - UI -> (Session, DB)
"""


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
        self.db = db
        self.console = Console()
        self.listener = keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release
        )
        self.listener.start()
        self.progess_bars = Progress(speed_estimate_period=5)


        self.key_pressed = None
        self.current_task_id = None
        self.objective = None
        self.duration_m = None
        self.current_session = None


    def on_press(self,key):
        try:
            self.key_pressed = key.char.lower()
        except AttributeError:
            pass

    def on_release(self,key):
        pass

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
            notifier = ToastNotifier()
            notifier.show_toast("DeepWork Timer: Task Finised",self.objective,duration=5)
            while notifier.notification_active():
                time.sleep(0.1)


    def event_loop(self):
        command_panel = Panel("(p)ause / (d)istraction / (q)uite / (r)esume",title="Commands")
        start_heading = Panel(f"[white]{self.objective}", style="green", title="Task")
        pause_heading = Panel(f"Paused Task: {self.objective}",style="red")

        self.console.print(RenderGroup(start_heading,command_panel))

        isLoop = True
        isPaused = False
        while isLoop:
            if self.key_pressed == 'q':
                self.key_pressed = None
                isLoop = False
                continue

            if self.key_pressed == 'p':
                # pause the timer, and don't alter the key_pressed
                self.console.clear()
                self.console.print(RenderGroup(pause_heading,command_panel))
                self.progess_bars.stop()
                isPaused = True
                self.key_pressed = None
                self.current_session.start_pause()
                continue

            if self.key_pressed == 'r':
                if isPaused:
                    self.console.clear()
                    self.console.print(RenderGroup(start_heading,command_panel))
                    self.progess_bars.start()
                    self.current_session.end_pause()

                isPaused = False
                self.key_pressed = None

            if self.key_pressed == 'd':
                self.current_session.register_distraction()
                self.key_pressed = None

            if isPaused:
                time.sleep(0.1)
                continue


            if not self.progess_bars.finished:
                time.sleep(1)
                self.progess_bars.update(self.current_task_id,advance=1)
            else:
                isLoop = False
                continue

    def main(self):
        while True:
            if not self.setup_event_loop():
                break            
            self.event_loop()
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
        

