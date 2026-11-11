"""Pixel Buddy - a pixel-art timer buddy with a task list and error-sound board.
Windows, Python 3.8+, no extra installs. Run:  python pixel_buddy.py
(rename to pixel_buddy.pyw to launch without a console window)
"""
import json, math, os, random, threading, time
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import winsound
except ImportError:  # not Windows: fall back to the Tk bell
    winsound = None

BG, PANEL, INK, MINT, GOLD, RED = "#1e1b2e", "#2b2745", "#f4f1ff", "#7be0c1", "#ffd166", "#ff5d73"
FONT = ("Consolas", 10, "bold")
PAL = {"K": "#14121f", "B": MINT, "R": RED, "D": "#14121f", "M": "#14121f", "Y": GOLD}
S = 10  # screen pixels per sprite pixel
PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PixelBuddy", "tasks.json")

BASE = [
    "................",
    ".......RR.......",
    ".......KK.......",
    "..KKKKKKKKKKKK..",
    ".KBBBBBBBBBBBBK.",
    ".KBBBBBBBBBBBBK.",
    ".KBBBBBBBBBBBBK.",
    ".KBBBBBBBBBBBBK.",
    ".KBBBBBBBBBBBBK.",
    ".KBBBBBBBBBBBBK.",
    ".KBBBBBBBBBBBBK.",
    "..KKKKKKKKKKKK..",
    "...KBBBBBBBBK...",
    "...KBBBBBBBBK...",
    "...KKK....KKK...",
    "................",
]

# name: (kind, data, buddy reaction)
SOUNDS = {
    "Windows Error": ("sys", 0x10, "error"),
    "Warning": ("sys", 0x30, "error"),
    "Question": ("sys", 0x20, "idle"),
    "Info ding": ("sys", 0x40, "done"),
    "Buzzer": ("seq", [(140, 500)], "error"),
    "Sad slide": ("seq", [(600, 150), (500, 150), (400, 200), (250, 500)], "error"),
    "Triple alarm": ("seq", [(1000, 120), (0, 60)] * 3, "error"),
    "Bonk": ("seq", [(220, 70), (110, 160)], "error"),
    "Glitch": ("glitch", None, "error"),
    "Level up": ("seq", [(523, 100), (659, 100), (784, 100), (1047, 250)], "done"),
}

MSG = {
    "idle": ["Pick a timer and I'll keep you company!", "Tiny steps count. Ready?"],
    "focus": ["You got this!", "One thing at a time.", "Just keep going...", "Almost there, keep it up!"],
    "rest": ["Rest... stretch... sip some water.", "Break time. Breathe!"],
    "done": ["Time's up! Nice work!", "Ding! You did it!"],
    "error": ["Bzzzt! Oops!", "Error! Error! ...jk."],
}


class App:
    def __init__(self, root):
        self.root = root
        root.title("Pixel Buddy")
        root.configure(bg=BG)
        root.resizable(False, False)
        self.t, self.mood, self.override, self.last = 0, "idle", ("", 0), ""
        self.total = self.remaining = 25 * 60
        self.running, self.end, self.is_break = False, 0.0, False
        self.lock = threading.Lock()
        self.tasks = self.load()
        self.build()
        self.refresh_tasks()
        self.show_time()
        self.tick()
        self.poll()

    # ---------- UI ----------
    def btn(self, parent, text, cmd, color=PANEL, fg=INK, **kw):
        return tk.Button(parent, text=text, command=cmd, bg=color, fg=fg, font=FONT, relief="flat", bd=0,
                         padx=8, pady=4, activebackground=MINT, activeforeground=BG, cursor="hand2", **kw)

    def build(self):
        r = self.root
        top = tk.Frame(r, bg=BG)
        top.pack(padx=12, pady=(12, 4))
        self.cv = tk.Canvas(top, width=200, height=200, bg=BG, highlightthickness=0)
        self.cv.grid(row=0, column=0)
        side = tk.Frame(top, bg=BG)
        side.grid(row=0, column=1, padx=(8, 0))
        self.time_lbl = tk.Label(side, text="25:00", font=("Consolas", 44, "bold"), fg=INK, bg=BG)
        self.time_lbl.pack()
        self.bar = tk.Canvas(side, width=220, height=14, bg=BG, highlightthickness=0)
        self.bar.pack()
        self.msg = tk.Label(side, text="", font=FONT, fg=GOLD, bg=PANEL, wraplength=200, justify="left",
                            padx=8, pady=8, width=24, height=3)
        self.msg.pack(pady=8)
        self.task_lbl = tk.Label(side, text="", font=FONT, fg=MINT, bg=BG, wraplength=220)
        self.task_lbl.pack()

        pre = tk.Frame(r, bg=BG)
        pre.pack(pady=4)
        for label, mins, brk in [("1m", 1, False), ("5m", 5, False), ("10m", 10, False),
                                 ("15m", 15, False), ("25m", 25, False), ("Break", 5, True)]:
            self.btn(pre, label, lambda m=mins, b=brk: self.start_new(m, b),
                     color="#3d6b8f" if brk else PANEL).pack(side="left", padx=3)

        ctl = tk.Frame(r, bg=BG)
        ctl.pack(pady=4)
        self.mins = tk.Spinbox(ctl, from_=1, to=180, width=4, font=FONT, justify="center")
        self.mins.delete(0, "end")
        self.mins.insert(0, "3")
        self.mins.pack(side="left")
        tk.Label(ctl, text="min", font=FONT, fg=INK, bg=BG).pack(side="left", padx=(2, 4))
        self.btn(ctl, "Go", self.start_custom).pack(side="left", padx=3)
        self.go_btn = self.btn(ctl, "Start", self.toggle, MINT, BG)
        self.go_btn.pack(side="left", padx=3)
        self.btn(ctl, "Reset", self.reset).pack(side="left", padx=3)

        st = ttk.Style()
        st.theme_use("clam")
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=PANEL, foreground=INK, padding=(14, 6), font=FONT)
        st.map("TNotebook.Tab", background=[("selected", MINT)], foreground=[("selected", BG)])
        nb = ttk.Notebook(r)
        nb.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        tf, sf = tk.Frame(nb, bg=PANEL), tk.Frame(nb, bg=PANEL)
        nb.add(tf, text=" Tasks ")
        nb.add(sf, text=" Sounds ")

        # tasks tab
        row = tk.Frame(tf, bg=PANEL)
        row.pack(fill="x", padx=8, pady=8)
        self.entry = tk.Entry(row, font=FONT, bg=BG, fg=INK, insertbackground=INK, relief="flat")
        self.entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.entry.bind("<Return>", lambda e: self.add_task())
        self.btn(row, "Add", self.add_task, MINT, BG).pack(side="left", padx=(6, 0))
        self.lb = tk.Listbox(tf, height=7, font=FONT, bg=BG, fg=INK, selectbackground=MINT, selectforeground=BG,
                             relief="flat", highlightthickness=0, exportselection=False, activestyle="none")
        self.lb.pack(fill="both", expand=True, padx=8)
        self.lb.bind("<Double-Button-1>", lambda e: self.toggle_task())
        self.lb.bind("<<ListboxSelect>>", lambda e: self.show_task())
        bar = tk.Frame(tf, bg=PANEL)
        bar.pack(pady=8)
        self.btn(bar, "Done / Undo", self.toggle_task).pack(side="left", padx=3)
        self.btn(bar, "Delete", self.delete_task).pack(side="left", padx=3)
        self.btn(bar, "Clear done", self.clear_done).pack(side="left", padx=3)

        # sounds tab
        tk.Label(sf, text="Click a sound (the buddy reacts!)", font=FONT, fg=INK, bg=PANEL).pack(pady=(8, 2))
        grid = tk.Frame(sf, bg=PANEL)
        grid.pack(padx=8, pady=4)
        for i, name in enumerate(SOUNDS):
            self.btn(grid, name, lambda n=name: self.play(n, True), BG, width=14).grid(row=i // 2, column=i % 2, padx=3, pady=3)
        arow = tk.Frame(sf, bg=PANEL)
        arow.pack(pady=8)
        tk.Label(arow, text="Timer alarm:", font=FONT, fg=INK, bg=PANEL).pack(side="left", padx=4)
        self.alarm = tk.StringVar(value="Level up")
        om = tk.OptionMenu(arow, self.alarm, *SOUNDS)
        om.config(bg=BG, fg=INK, font=FONT, relief="flat", highlightthickness=0, activebackground=MINT)
        om["menu"].config(bg=BG, fg=INK, font=FONT)
        om.pack(side="left")

    # ---------- buddy ----------
    def state(self):
        st, until = self.override
        return st if self.t < until else self.mood

    def react(self, st, ticks=6):
        self.override = (st, self.t + ticks)

    def tick(self):
        self.t += 1
        self.draw()
        self.root.after(250, self.tick)

    def draw(self):
        st, t = self.state(), self.t
        if st != self.last or (st == "focus" and t % 40 == 0):
            self.msg.config(text=random.choice(MSG.get(st, MSG["idle"])))
            self.last = st
        g = [list(r) for r in BASE]

        def put(c, pts):
            for x, y in pts:
                g[y][x] = c

        eyes = [(4, 6), (5, 6), (4, 7), (5, 7), (10, 6), (11, 6), (10, 7), (11, 7)]
        dx = dy = 0
        if st == "done":
            put("D", [(4, 7), (5, 6), (6, 7), (9, 7), (10, 6), (11, 7)])
            put("M", [(5, 8), (6, 9), (7, 9), (8, 9), (9, 9), (10, 8)])
            dy = -2 if t % 2 else 0
        elif st == "error":
            put("D", [(3, 6), (5, 6), (4, 7), (3, 8), (5, 8), (10, 6), (12, 6), (11, 7), (10, 8), (12, 8)])
            put("M", [(5, 10), (6, 9), (7, 9), (8, 9), (9, 9), (10, 10)])
            dx = 1 if t % 2 else -1
            if t % 2:
                put("Y", [(7, 1), (8, 1)])
        elif st == "rest":
            put("D", [(4, 7), (5, 7), (10, 7), (11, 7)])
            put("M", [(7, 9), (8, 9)])
            dy = (t // 2) % 2
        else:
            blink = t % 12 == 0
            put("D", [(x, y) for x, y in eyes if not blink or y == 7])
            put("M", [(7, 9), (8, 9)] if st == "idle" else [(6, 9), (7, 9), (8, 9), (9, 9)])
            dy = (t // 2) % 2
        c = self.cv
        c.delete("all")
        ox, oy = 20 + dx * S, 20 + dy * S
        for y, row in enumerate(g):
            for x, ch in enumerate(row):
                if ch != ".":
                    c.create_rectangle(ox + x * S, oy + y * S, ox + (x + 1) * S, oy + (y + 1) * S,
                                       fill=PAL[ch], width=0)
        if st == "done":
            for _ in range(10):
                px, py = random.randint(0, 195), random.randint(0, 195)
                c.create_rectangle(px, py, px + 5, py + 5, fill=random.choice([GOLD, RED, MINT, INK]), width=0)
        if st == "rest":
            c.create_text(170, 50 - (t % 4) * 5, text="z", font=("Consolas", 14 + (t % 3) * 4, "bold"), fill=GOLD)

    # ---------- timer ----------
    def show_time(self):
        m, s = divmod(max(0, math.ceil(self.remaining)), 60)
        self.time_lbl.config(text=f"{m:02d}:{s:02d}")
        filled = round(22 * (1 - self.remaining / self.total)) if self.total else 0
        self.bar.delete("all")
        for i in range(22):
            self.bar.create_rectangle(i * 10, 0, i * 10 + 8, 14, width=0, fill=GOLD if i < filled else PANEL)

    def start_new(self, mins, brk=False):
        self.total = self.remaining = mins * 60
        self.is_break, self.running = brk, False
        self.toggle()

    def start_custom(self):
        try:
            m = max(1, min(180, int(self.mins.get())))
        except ValueError:
            self.react("error", 6)
            return
        self.start_new(m)

    def toggle(self):
        if self.running:
            self.remaining = max(0, self.end - time.monotonic())
            self.running, self.mood = False, "idle"
            self.go_btn.config(text="Resume")
        else:
            if self.remaining <= 0:
                self.remaining = self.total
            self.end = time.monotonic() + self.remaining
            self.running = True
            self.mood = "rest" if self.is_break else "focus"
            self.go_btn.config(text="Pause")
        self.show_time()

    def reset(self):
        self.running, self.mood, self.remaining = False, "idle", self.total
        self.go_btn.config(text="Start")
        self.root.title("Pixel Buddy")
        self.show_time()

    def poll(self):
        if self.running:
            self.remaining = self.end - time.monotonic()
            if self.remaining <= 0:
                self.finish()
            else:
                self.show_time()
                self.root.title(f"{self.time_lbl['text']} - Pixel Buddy")
        self.root.after(200, self.poll)

    def finish(self):
        was_break = self.is_break
        self.running, self.remaining, self.mood = False, 0, "idle"
        self.show_time()
        self.react("done", 28)
        self.go_btn.config(text="Start")
        self.root.title("Time's up! - Pixel Buddy")
        self.play(self.alarm.get())
        self.root.after(900, lambda: self.play(self.alarm.get()))
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(2000, lambda: self.root.attributes("-topmost", False))
        i = self.selected()
        if i is not None and not was_break:
            self.root.after(300, lambda: self.ask_done(i))

    def ask_done(self, i):
        if i >= len(self.tasks):
            return
        t = self.tasks[i]
        t["n"] += 1
        if messagebox.askyesno("Pixel Buddy", f"Session finished on:\n{t['text']}\n\nMark it done?"):
            t["done"] = True
        self.refresh_tasks(i)

    # ---------- sounds ----------
    def play(self, name, react=False):
        kind, data, mood = SOUNDS[name]
        if react:
            self.react(mood, 6)
        if kind == "glitch":
            kind, data = "seq", [(random.randint(150, 2500), 35) for _ in range(12)]
        if not winsound:
            self.root.bell()
            return

        def run():
            with self.lock:
                if kind == "sys":
                    winsound.MessageBeep(data)
                    time.sleep(0.6)
                else:
                    for f, ms in data:
                        winsound.Beep(f, ms) if f else time.sleep(ms / 1000)

        threading.Thread(target=run, daemon=True).start()

    # ---------- tasks ----------
    def load(self):
        try:
            with open(PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def save(self):
        try:
            os.makedirs(os.path.dirname(PATH), exist_ok=True)
            with open(PATH, "w", encoding="utf-8") as f:
                json.dump(self.tasks, f, indent=1)
        except OSError:
            pass

    def selected(self):
        s = self.lb.curselection()
        return s[0] if s else None

    def refresh_tasks(self, keep=None):
        self.lb.delete(0, "end")
        for i, t in enumerate(self.tasks):
            self.lb.insert("end", f"[{'x' if t['done'] else ' '}] {t['text']}" + (f"  (x{t['n']})" if t["n"] else ""))
            if t["done"]:
                self.lb.itemconfig(i, fg="#7d7a96")
        if keep is not None and keep < len(self.tasks):
            self.lb.selection_set(keep)
        self.show_task()
        self.save()

    def show_task(self):
        i = self.selected()
        self.task_lbl.config(text=f"Focus: {self.tasks[i]['text']}" if i is not None else "")

    def add_task(self):
        text = self.entry.get().strip()
        if text:
            self.tasks.append({"text": text, "done": False, "n": 0})
            self.entry.delete(0, "end")
            self.refresh_tasks(len(self.tasks) - 1)

    def toggle_task(self):
        i = self.selected()
        if i is not None:
            self.tasks[i]["done"] = not self.tasks[i]["done"]
            if self.tasks[i]["done"]:
                self.react("done", 8)
            self.refresh_tasks(i)

    def delete_task(self):
        i = self.selected()
        if i is not None:
            self.tasks.pop(i)
            self.refresh_tasks()

    def clear_done(self):
        self.tasks = [t for t in self.tasks if not t["done"]]
        self.refresh_tasks()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
