"""Publishing Split Calculator."""
import math, logging

class PubSplitCalculator:
    def __init__(self, sm): self.sheets = sm; self._cache = None

    def _load(self):
        if self._cache is not None: return self._cache
        try:
            data = self.sheets.get_all_rows('Personnel')
            if not data: self._cache = {}; return {}
            h = data[0]; rows = data[1:]
            def fc(t):
                for i, c in enumerate(h):
                    if t.lower() in c.lower(): return i
                return None
            nc, pc, prc, ac = fc('name'), None, None, None
            # More precise matching for publisher, PRO, and administrator
            for i, c in enumerate(h):
                cl = c.lower().strip()
                if cl in ('publishing company', 'publisher', 'pub company') and pc is None: pc = i
                if cl == 'pro' and prc is None: prc = i
                if cl in ('administrator', 'admin company', 'pub admin', 'administered by') and ac is None: ac = i
            # Fallback if exact match didn't work
            if pc is None: pc = fc('publishing company')
            if pc is None: pc = fc('publisher')
            if prc is None: prc = fc('pro')
            if ac is None: ac = fc('administrator')
            if ac is None: ac = fc('administered by')
            lu = {}
            for r in rows:
                n = str(r[nc]).strip() if nc and nc < len(r) else ''
                if n:
                    lu[n.lower()] = {
                        'name': n,
                        'publisher': str(r[pc]).strip() if pc is not None and pc < len(r) else '',
                        'pro': str(r[prc]).strip() if prc is not None and prc < len(r) else '',
                        'admin': str(r[ac]).strip() if ac is not None and ac < len(r) else ''
                    }
            self._cache = lu; return lu
        except Exception as e:
            logging.warning(f"PubSplitCalculator load: {e}")
            self._cache = {}; return {}

    def lookup_writer(self, name):
        p = self._load(); nl = name.strip().lower()
        if nl in p: return p[nl]
        for k,v in p.items():
            if nl in k or k in nl: return v
        return {'name':name,'publisher':'','pro':'','admin':''}

    def calculate(self, writers, mode='equal', vocalist=None):
        if not writers: return {'splits':[],'formatted':'','error':'No writers'}
        if mode=='equal': splits = self._eq(writers, vocalist)
        elif mode=='hiphop': splits = self._hp(writers, vocalist)
        else: splits = [{'name':w.get('name',''),'percentage':float(w.get('percentage',0)),'publisher':w.get('publisher',''),'pro':w.get('pro',''),'admin':w.get('admin',''),'is_vocalist':False} for w in writers]
        for s in splits:
            info = self.lookup_writer(s['name'])
            if not s.get('publisher'): s['publisher'] = info.get('publisher','')
            if not s.get('pro'): s['pro'] = info.get('pro','')
            if not s.get('admin'): s['admin'] = info.get('admin','')
        t = sum(s['percentage'] for s in splits)
        parts = []
        for s in splits:
            parts.append(self._format_credit(s))
        return {'splits':splits,'formatted':' / '.join(parts),'total':round(t,2),'valid':abs(t-100)<0.01}

    @staticmethod
    def _format_credit(s):
        """Format a single credit line like Airtable:
        33.33% Ben Wylen [Restless Youth Entertainment (BMI)] administered by Rightsbridge (PRS)]
        """
        c = f"{s['percentage']:.2f}% {s['name']}"
        pub = s.get('publisher', '')
        pro = s.get('pro', '')
        admin = s.get('admin', '')
        if pub and pro:
            c += f" [{pub} ({pro})]"
        elif pub:
            c += f" [{pub}]"
        elif pro:
            c += f" [({pro})]"
        if admin:
            # Admin may include its own PRO in parentheses already
            c += f" administered by {admin}"
        return c

    def _eq(self, w, v):
        n=len(w); b=math.floor(10000/n)/100; rem=round(100-(b*n),2)
        splits=[]
        for wr in w:
            pct=b; nm=wr.get('name',''); iv=v and nm.lower()==v.lower()
            if iv: pct=round(pct+rem,2)
            elif not v and not splits: pct=round(pct+rem,2)
            splits.append({'name':nm,'percentage':pct,'publisher':wr.get('publisher',''),'pro':wr.get('pro',''),'admin':wr.get('admin',''),'is_vocalist':bool(iv)})
        t=sum(s['percentage'] for s in splits)
        if abs(t-100)>0.01 and splits: splits[0]['percentage']=round(splits[0]['percentage']+(100-t),2)
        return splits

    def _hp(self, w, v):
        pr=[x for x in w if x.get('role','').lower() in ['producer','prod']]; ly=[x for x in w if x not in pr]
        if not pr: return self._eq(w, v)
        splits=[]
        pe=round(50/len(pr),2)
        for p in pr: splits.append({'name':p.get('name',''),'percentage':pe,'publisher':p.get('publisher',''),'pro':p.get('pro',''),'admin':p.get('admin',''),'is_vocalist':False})
        if ly:
            we=math.floor((50/len(ly))*100)/100; rem=round(50-(we*len(ly)),2)
            for i,wr in enumerate(ly):
                pct=we; iv=v and wr.get('name','').lower()==v.lower()
                if iv: pct=round(pct+rem,2)
                elif i==0 and not v: pct=round(pct+rem,2)
                splits.append({'name':wr.get('name',''),'percentage':pct,'publisher':wr.get('publisher',''),'pro':wr.get('pro',''),'admin':wr.get('admin',''),'is_vocalist':bool(iv)})
        t=sum(s['percentage'] for s in splits)
        if abs(t-100)>0.01 and splits: splits[0]['percentage']=round(splits[0]['percentage']+(100-t),2)
        return splits
