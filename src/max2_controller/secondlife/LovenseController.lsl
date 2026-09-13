// Lovense wearable — NO tunnel.
// The PC app polls THIS object's SL URL (HTTP-in).
// Wear on Head/Chest. Copy the PAIR URL into Lovense Controller.

string  TOKEN    = "PASTE_TOKEN_FROM_GUI";
string  NOTECARD_NAME = "lovense.cfg";
integer ATTACH_POINT = 2;
float   DEFAULT_TIME = 4.0;
integer PUBLIC = TRUE;
string  HOVER = ""; // owner hover text; empty = default title

integer PROMPT_NONE = 0;
integer PROMPT_TOKEN = 1;
integer PROMPT_HOVER = 2;

key     gUrlReq;
string  gUrl;
key     gNoteQuery;
key     gUser;
key     gAim;
integer gLine;
integer gNotePending;
integer gMenuChan;
integer gMenuListen;
integer gPromptKind;
integer gAttachTried;
integer gConnected;
integer gVib;
integer gVMax;
integer gPump;
integer gShowText;
integer gPaired;
float   gCoolAt;
string  gPend; // action payload, consumed by PC GET
integer gUses;
integer gOrbit;
string  gNeedsTxt;
string  gTipTxt;
string  gEnerTxt;

string JsonEsc(string s)
{
    integer i;
    string o = "";
    integer n = llStringLength(s);
    for (i = 0; i < n; ++i)
    {
        string c = llGetSubString(s, i, i);
        if (c == "\\") o += "\\\\";
        else if (c == "\"") o += "\\\"";
        else o += c;
    }
    return o;
}

string HoverUnescape(string s)
{
    integer p = llSubStringIndex(s, "\\n");
    while (p >= 0)
    {
        s = llGetSubString(s, 0, p - 1) + "\n" + llGetSubString(s, p + 2, -1);
        p = llSubStringIndex(s, "\\n");
    }
    return s;
}

integer LoadUses()
{
    string d = llGetObjectDesc();
    integer p = llSubStringIndex(llToLower(d), "uses=");
    if (p < 0) return 0;
    return (integer)llGetSubString(d, p + 5, -1);
}

SaveUses()
{
    llSetObjectDesc("touch=control uses=" + (string)gUses);
    llLinksetDataWrite("lv.uses", (string)gUses);
}

integer NeedsChan()
{
    return 0xC07E0000 ^ (integer)("0x" + llGetSubString((string)llGetOwner(), 0, 7));
}

PulseNeeds(string kind)
{
    integer vmax = gVMax;
    if (vmax < 1) vmax = 20;
    string msg = "LV|" + kind + "|" + (string)gVib + "|" + (string)vmax;
    llMessageLinked(LINK_SET, 0xC07E, msg, NULL_KEY);
    llRegionSay(NeedsChan(), msg);
}

integer TokenMissing()
{
    return (TOKEN == "" || TOKEN == "PASTE_TOKEN_FROM_GUI" || TOKEN == "WKLEJ_TOKEN_Z_GUI");
}

integer TokenLooksOk(string t)
{
    if (t == "" || t == "PASTE_TOKEN_FROM_GUI" || t == "WKLEJ_TOKEN_Z_GUI")
        return FALSE;
    return TRUE;
}

SaveCfg()
{
    llLinksetDataWrite("lv.ok", "1");
    // Never overwrite a stored token with the placeholder.
    if (!TokenMissing())
    {
        llLinksetDataWrite("lv.token", TOKEN);
        llLinksetDataWrite("lv.tok", TOKEN);
    }
    llLinksetDataWrite("lv.public", (string)PUBLIC);
    llLinksetDataWrite("lv.hover", HOVER);
    llLinksetDataWrite("lv.time", (string)DEFAULT_TIME);
    llLinksetDataWrite("lv.show", (string)gShowText);
    llLinksetDataWrite("lv.uses", (string)gUses);
    llLinksetDataWrite("lv.orbit", (string)gOrbit);
}

LoadCfg()
{
    string t = llLinksetDataRead("lv.token");
    if (!TokenLooksOk(t)) t = llLinksetDataRead("lv.tok");
    if (TokenLooksOk(t)) TOKEN = t;
    if (llLinksetDataRead("lv.ok") != "1")
    {
        if (!TokenMissing()) SaveCfg();
        return;
    }
    string p = llLinksetDataRead("lv.public");
    if (p != "") PUBLIC = (integer)p;
    HOVER = llLinksetDataRead("lv.hover");
    string tm = llLinksetDataRead("lv.time");
    if (tm != "") DEFAULT_TIME = (float)tm;
    string sh = llLinksetDataRead("lv.show");
    if (sh != "") gShowText = (integer)sh;
    string u = llLinksetDataRead("lv.uses");
    if (u != "") gUses = (integer)u;
    string o = llLinksetDataRead("lv.orbit");
    if (o != "") gOrbit = (integer)o;
}

string ClipHover(string s)
{
    // llSetText ~254 bytes; leave room for status line
    if (llStringLength(s) > 180) s = llGetSubString(s, 0, 179);
    return s;
}

vector HoverColor()
{
    vector tc = <1.00, 0.82, 0.90>;
    string col = llLinksetDataRead("lv.color");
    if (col == "") return tc;
    list p = llParseString2List(col, [" "], []);
    if (llGetListLength(p) < 3) return tc;
    return <(float)llList2String(p, 0), (float)llList2String(p, 1), (float)llList2String(p, 2)>;
}

integer TokenOk(key id, string body)
{
    if (TokenMissing()) return TRUE;
    string qs = llGetHTTPHeader(id, "x-query-string");
    string qtok = "";
    integer p = llSubStringIndex(llToLower(qs), "token=");
    if (p >= 0)
    {
        qtok = llGetSubString(qs, p + 6, -1);
        integer a = llSubStringIndex(qtok, "&");
        if (a >= 0) qtok = llGetSubString(qtok, 0, a - 1);
    }
    string htok = llGetHTTPHeader(id, "x-api-token");
    string btok = "";
    if (body != "")
    {
        string j = llJsonGetValue(body, ["token"]);
        if (j != JSON_INVALID) btok = j;
    }
    if (qtok == TOKEN || htok == TOKEN || btok == TOKEN) return TRUE;
    return FALSE;
}

string LiveBar(float x)
{
    integer n = (integer)(x * 10.0 + 0.5);
    if (n < 0) n = 0;
    if (n > 10) n = 10;
    string s = "";
    integer i;
    for (i = 0; i < 10; ++i)
    {
        if (i < n) s += "●";
        else s += "○";
    }
    return s;
}

float VibeX()
{
    integer vmax = gVMax;
    if (vmax < 1) vmax = 20;
    float x = 0.0;
    if (gConnected && gVib > 0) x = (float)gVib / (float)vmax;
    if (x > 1.0) x = 1.0;
    return x;
}

PulseLook()
{
    llMessageLinked(LINK_SET, 0xC07E,
        "LOOK|fx|" + (string)gVib + "|" + (string)gVMax + "|"
        + (string)gConnected + "|" + (string)gPaired + "|"
        + (string)gAim, NULL_KEY);
}

Paint()
{
    float x = VibeX();
    PulseLook();
    string body = "";
    vector tc = HoverColor();
    if (gShowText)
    {
        string line;
        if (gUrl == "")
            line = "getting URL…";
        else if (!gPaired)
            line = "paste PAIR URL in app";
        else
        {
            integer pct = (integer)(x * 100.0 + 0.5);
            if (!gConnected && gVib <= 0)
                line = LiveBar(0.0) + "  PC · no toy";
            else
            {
                line = LiveBar(x) + "  " + (string)pct + "%";
                if (gPump > 0) line += "  P" + (string)gPump;
            }
            line += "\nuses " + (string)gUses;
        }
        string title = HOVER;
        if (title == "") title = "✦  Lovense";
        body = title + "\n" + line;
    }
    if (gEnerTxt != "")
    {
        if (body != "") body += "\n";
        body += gEnerTxt;
    }
    if (gTipTxt != "")
    {
        if (body != "") body += "\n";
        body += gTipTxt;
    }
    if (gNeedsTxt != "")
    {
        if (body != "") body += "\n";
        body += gNeedsTxt;
    }
    if (body == "")
    {
        llSetText("", ZERO_VECTOR, 0.0);
        return;
    }
    if (llStringLength(body) > 250) body = llGetSubString(body, 0, 249);
    llSetText(body, tc, 1.0);
}

ClickMode()
{
    // Orb is always a touch menu. Pay lives on the ground tip-jar vessel.
    llSetClickAction(CLICK_ACTION_TOUCH);
    llSetLinkPrimitiveParamsFast(LINK_SET, [PRIM_CLICK_ACTION, CLICK_ACTION_TOUCH]);
}

SetupLook()
{
    ClickMode();
    Paint();
    llMessageLinked(LINK_SET, 0xC07E, "LOOK|init", NULL_KEY);
}

AskUrl()
{
    if (gUrl != "")
    {
        llReleaseURL(gUrl);
        gUrl = "";
    }
    gPaired = FALSE;
    gUrlReq = llRequestSecureURL();
    Paint();
}

SayPair()
{
    if (gUrl == "")
    {
        llOwnerSay("PAIR URL not ready yet — click URL again in a moment.");
        return;
    }
    llOwnerSay("PAIR URL — paste in Lovense Controller → Second Life:");
    llOwnerSay(gUrl);
}

Tell(key who, string m)
{
    if (who == NULL_KEY || who == llGetOwner()) llOwnerSay(m);
    else
        llInstantMessage(who, m);
}

OpenListen(key who)
{
    gMenuChan = 0x80000000 | (integer)llFrand(0x7FFFFFFF);
    llListenRemove(gMenuListen);
    gMenuListen = llListen(gMenuChan, "", who, "");
}

Queue(string pend)
{
    if (pend != "stop")
    {
        if (gUser != NULL_KEY) gAim = gUser;
        gUses += 1;
        SaveUses();
        PulseNeeds("queue");
        if (!gConnected)
        {
            llMessageLinked(LINK_SET, 0xC07E, "EN|add|" + pend, gUser);
            Paint();
            if (gUser != NULL_KEY && gUser != llGetOwner())
                Tell(gUser, "stored to energy");
            return;
        }
        gPend = pend;
    }
    else
    {
        gPend = "stop";
        gVib = 0;
        gAim = NULL_KEY;
        PulseNeeds("stop");
    }
    Paint();
    if (!gPaired)
        llOwnerSay("queued uses=" + (string)gUses + " — PC NOT paired. Touch → URL, paste PAIR URL in the app.");
    else
        llOwnerSay("queued uses=" + (string)gUses);
    if (gUser != NULL_KEY && gUser != llGetOwner())
        Tell(gUser, "queued · uses " + (string)gUses);
}

// Tip jar / extra objects: LVQ|i|0.5|8   LVQ|v|12|6   LVQ|p|pulse|10   LVQ|stop
ApplyCmd(string msg)
{
    if (llGetSubString(msg, 0, 3) != "LVQ|") return;
    list p = llParseString2List(msg, ["|"], []);
    string k = llList2String(p, 1);
    if (k == "stop")
    {
        Queue("stop");
        return;
    }
    if (k == "i" || k == "v" || k == "p")
        Queue(k + "|" + llList2String(p, 2) + "|" + llList2String(p, 3));
    else if (k == "r")
        Queue(k + "|" + llList2String(p, 2) + "|" + llList2String(p, 3)
            + "|" + llList2String(p, 4));
}

ApplyBuzz(string str, key payer)
{
    // TJ|buzz|i|0.28|6|<payer>
    list p = llParseString2List(str, ["|"], []);
    if (llList2String(p, 0) != "TJ" || llList2String(p, 1) != "buzz") return;
    key who = (key)llList2String(p, 5);
    if (who == NULL_KEY) who = payer;
    if (who != NULL_KEY)
    {
        gUser = who;
        gAim = who;
    }
    string k = llList2String(p, 2);
    if (k == "stop") Queue("stop");
    else if (k == "i" || k == "v" || k == "p")
        Queue(k + "|" + llList2String(p, 3) + "|" + llList2String(p, 4));
    else if (k == "r")
        Queue(k + "|" + llList2String(p, 3) + "|" + llList2String(p, 4)
            + "|" + llList2String(p, 5));
}

string StLine()
{
    if (!gPaired) return "not paired";
    if (!gConnected) return "off";
    return (string)gVib + "/" + (string)gVMax;
}

MenuMain()
{
    gPromptKind = PROMPT_NONE;
    OpenListen(gUser);
    list b = ["STOP", "Power", "Presets", "Long",
              "Patterns", "50%", "MAX", "25%",
              "75%", "URL"];
    if (gUser == llGetOwner())
        b += ["Setup", "Rez jar"];
    else
        b += ["Help", "-"];
    llDialog(gUser, "Lovense [" + StLine() + "]\none click = this menu", b, gMenuChan);
}

MenuPower()
{
    OpenListen(gUser);
    llDialog(gUser, "Power " + (string)((integer)DEFAULT_TIME) + "s",
        ["0", "5", "10", "15", "20", "30%", "60%", "«"], gMenuChan);
}

MenuPresets()
{
    OpenListen(gUser);
    llDialog(gUser, "Presets",
        ["Pulse", "Wave", "Fireworks", "Earthquake",
         "Tease", "Edge", "Heartbeat", "«"], gMenuChan);
}

MenuLong()
{
    OpenListen(gUser);
    llDialog(gUser, "Long",
        ["Slowburn", "Marathon", "Crescendo", "Afterglow",
         "Imperial", "«", "-", "-"], gMenuChan);
}

MenuPat()
{
    OpenListen(gUser);
    llDialog(gUser, "Patterns",
        ["Strobe", "Build", "Swing", "Sine", "Ramp", "Imperial", "«", "-"],
        gMenuChan);
}

MenuSetup()
{
    if (gUser != llGetOwner()) return;
    OpenListen(gUser);
    string lock = "Unlock";
    if (PUBLIC) lock = "Lock";
    string orb = "Orbit off";
    if (!gOrbit) orb = "Orbit on";
    list b = ["Hover", "Token", lock, "Needs",
              "Hide text", "Show text", orb, "Stats",
              "Color", "Tip jar", "Rez jar", "Help"];
    llDialog(gUser, "Setup  PUBLIC=" + (string)PUBLIC + "  uses=" + (string)gUses,
        b, gMenuChan);
}

MenuStats()
{
    if (gUser != llGetOwner()) return;
    OpenListen(gUser);
    string tips = gTipTxt;
    if (tips == "") tips = "none";
    llDialog(gUser,
        "Stats\nuses " + (string)gUses + "\ntips " + tips,
        ["Clear uses", "Clear tips", "Clear all", "Replay",
         "Clear E", "«", "-", "-"],
        gMenuChan);
}

ClearUses()
{
    gUses = 0;
    SaveUses();
    Paint();
    llOwnerSay("Uses reset to 0.");
}

ClearTips()
{
    gTipTxt = "";
    Paint();
    llMessageLinked(LINK_SET, 0xC07E, "JAR|reset", gUser);
    llOwnerSay("Tip totals reset.");
}

Help()
{
    Tell(gUser, "One click = one menu. PC app polls this object (no tunnel).");
    if (gUser == llGetOwner())
    {
        Tell(gUser, "Rez jar needs LovenseJarHost in this Glass plus a COPY named LovenseTipJar.");
        SayPair();
        llOwnerSay("PUBLIC=" + (string)PUBLIC);
    }
}

integer OnBtn(string msg)
{
    if (msg == "-" || msg == " " || msg == "✖") return TRUE;
    if (msg == "«") { MenuMain(); return TRUE; }
    if (msg == "URL") { if (gUser == llGetOwner()) SayPair(); return TRUE; }
    if (msg == "STOP") { Queue("stop"); return TRUE; }
    if (msg == "Power") { MenuPower(); return TRUE; }
    if (msg == "Presets") { MenuPresets(); return TRUE; }
    if (msg == "Long") { MenuLong(); return TRUE; }
    if (msg == "Patterns") { MenuPat(); return TRUE; }
    if (msg == "Setup")
    {
        if (gUser == llGetOwner()) MenuSetup();
        return TRUE;
    }
    if (msg == "Hover")
    {
        if (gUser != llGetOwner()) return TRUE;
        OpenListen(llGetOwner());
        gPromptKind = PROMPT_HOVER;
        string cur = HOVER;
        if (cur == "") cur = "(default: ✦  Lovense)";
        llTextBox(llGetOwner(),
            "Hover text over the bar.\nEmpty = default.\nUse \\n for a new line.\nNow: " + cur,
            gMenuChan);
        return TRUE;
    }
    if (msg == "Token")
    {
        if (gUser != llGetOwner()) return TRUE;
        OpenListen(llGetOwner());
        gPromptKind = PROMPT_TOKEN;
        llTextBox(llGetOwner(), "TOKEN (empty=cancel)", gMenuChan);
        return TRUE;
    }
    if (msg == "Lock")
    {
        if (gUser == llGetOwner())
        {
            PUBLIC = FALSE;
            SaveCfg();
            llOwnerSay("Locked — owner only.");
        }
        return TRUE;
    }
    if (msg == "Unlock")
    {
        if (gUser == llGetOwner())
        {
            PUBLIC = TRUE;
            SaveCfg();
            llOwnerSay("Unlocked — anyone can control.");
        }
        return TRUE;
    }
    if (msg == "Stats")
    {
        if (gUser == llGetOwner()) MenuStats();
        return TRUE;
    }
    if (msg == "Clear uses" || msg == "Reset #")
    {
        if (gUser == llGetOwner()) ClearUses();
        return TRUE;
    }
    if (msg == "Clear tips")
    {
        if (gUser == llGetOwner()) ClearTips();
        return TRUE;
    }
    if (msg == "Clear all")
    {
        if (gUser == llGetOwner())
        {
            ClearUses();
            ClearTips();
        }
        return TRUE;
    }
    if (msg == "Replay")
    {
        if (gUser == llGetOwner())
        {
            gPend = "replay";
            llOwnerSay("Replay queued — connect the toy on the PC.");
        }
        return TRUE;
    }
    if (msg == "Clear E")
    {
        if (gUser == llGetOwner())
        {
            gPend = "clearbank";
            gEnerTxt = "";
            llMessageLinked(LINK_SET, 0xC07E, "EN|clear", gUser);
            Paint();
        }
        return TRUE;
    }
    if (msg == "Color")
    {
        if (gUser == llGetOwner())
            llMessageLinked(LINK_SET, 0xC07E, "EN|color", gUser);
        return TRUE;
    }
    if (msg == "Orbit off")
    {
        if (gUser == llGetOwner())
        {
            gOrbit = FALSE;
            SaveCfg();
            llMessageLinked(LINK_SET, 0xC07E, "LOOK|orbit|0", NULL_KEY);
            llOwnerSay("Orbit off.");
        }
        return TRUE;
    }
    if (msg == "Orbit on")
    {
        if (gUser == llGetOwner())
        {
            gOrbit = TRUE;
            SaveCfg();
            llMessageLinked(LINK_SET, 0xC07E, "LOOK|orbit|1", NULL_KEY);
            llOwnerSay("Orbit on.");
        }
        return TRUE;
    }
    if (msg == "Needs")
    {
        if (gUser == llGetOwner())
            llMessageLinked(LINK_SET, 0xC07E, "NEEDSMENU", gUser);
        return TRUE;
    }
    if (msg == "Tip jar")
    {
        if (gUser == llGetOwner())
            llMessageLinked(LINK_SET, 0xC07E, "JAR|menu", gUser);
        return TRUE;
    }
    if (msg == "Rez jar")
    {
        if (gUser == llGetOwner())
            llMessageLinked(LINK_SET, 0xC07E, "JAR|rez", gUser);
        return TRUE;
    }
    if (msg == "Hide text")
    {
        gShowText = FALSE;
        SaveCfg();
        Paint();
        return TRUE;
    }
    if (msg == "Show text")
    {
        gShowText = TRUE;
        SaveCfg();
        Paint();
        return TRUE;
    }
    if (msg == "Help") { Help(); return TRUE; }
    if (msg == "25%") { Queue("i|0.25|" + (string)DEFAULT_TIME); return TRUE; }
    if (msg == "50%") { Queue("i|0.50|" + (string)DEFAULT_TIME); return TRUE; }
    if (msg == "75%") { Queue("i|0.75|" + (string)DEFAULT_TIME); return TRUE; }
    if (msg == "30%") { Queue("i|0.30|" + (string)DEFAULT_TIME); return TRUE; }
    if (msg == "60%") { Queue("i|0.60|" + (string)DEFAULT_TIME); return TRUE; }
    if (msg == "MAX") { Queue("i|1.0|" + (string)DEFAULT_TIME); return TRUE; }
    if (msg == "0" || msg == "5" || msg == "10" || msg == "15" || msg == "20")
    { Queue("v|" + msg + "|" + (string)DEFAULT_TIME); return TRUE; }
    if (msg == "Pulse") { Queue("p|pulse|10"); return TRUE; }
    if (msg == "Wave") { Queue("p|wave|12"); return TRUE; }
    if (msg == "Fireworks") { Queue("p|fireworks|10"); return TRUE; }
    if (msg == "Earthquake") { Queue("p|earthquake|12"); return TRUE; }
    if (msg == "Tease") { Queue("p|tease|15"); return TRUE; }
    if (msg == "Edge") { Queue("p|edge|14"); return TRUE; }
    if (msg == "Heartbeat") { Queue("p|heartbeat|16"); return TRUE; }
    if (msg == "Slowburn") { Queue("p|slowburn|45"); return TRUE; }
    if (msg == "Marathon") { Queue("p|marathon|60"); return TRUE; }
    if (msg == "Crescendo") { Queue("p|crescendo|40"); return TRUE; }
    if (msg == "Afterglow") { Queue("p|afterglow|35"); return TRUE; }
    if (msg == "Imperial") { Queue("p|imperial|24"); return TRUE; }
    if (msg == "Strobe") { Queue("r|20;0;20;0;20;0|200|10"); return TRUE; }
    if (msg == "Build") { Queue("r|4;8;12;16;20;16;12;8|120|12"); return TRUE; }
    if (msg == "Swing") { Queue("r|20;15;10;5;10;15;20|150|12"); return TRUE; }
    if (msg == "Sine") { Queue("r|5;10;15;20;15;10;5|220|16"); return TRUE; }
    if (msg == "Ramp") { Queue("r|2;6;10;14;18;20;14;8;2|300|20"); return TRUE; }
    return FALSE;
}

string PendJson()
{
    if (gPend == "replay") return "{\"action\":\"replay\"}";
    if (gPend == "clearbank") return "{\"action\":\"clearbank\"}";
    if (gPend == "") return "null";
    if (gPend == "stop") return "{\"action\":\"stop\"}";
    list p = llParseString2List(gPend, ["|"], []);
    string k = llList2String(p, 0);
    if (k == "v")
        return "{\"action\":\"vibrate\",\"level\":" + llList2String(p, 1)
            + ",\"time\":" + llList2String(p, 2) + "}";
    if (k == "i")
        return "{\"action\":\"intensity\",\"i\":" + llList2String(p, 1)
            + ",\"time\":" + llList2String(p, 2) + "}";
    if (k == "p")
        return "{\"action\":\"preset\",\"name\":\"" + JsonEsc(llList2String(p, 1))
            + "\",\"time\":" + llList2String(p, 2) + "}";
    if (k == "r")
        return "{\"action\":\"pattern\",\"strength\":\"" + JsonEsc(llList2String(p, 1))
            + "\",\"interval\":" + llList2String(p, 2)
            + ",\"time\":" + llList2String(p, 3) + "}";
    return "null";
}

CfgLine(string line)
{
    line = llStringTrim(line, STRING_TRIM);
    if (line == "" || llGetSubString(line, 0, 0) == "#") return;
    integer eq = llSubStringIndex(line, "=");
    if (eq < 1) return;
    string k = llToLower(llStringTrim(llGetSubString(line, 0, eq - 1), STRING_TRIM));
    string v = llStringTrim(llGetSubString(line, eq + 1, -1), STRING_TRIM);
    if (k == "token")
    {
        if (TokenLooksOk(v)) TOKEN = v;
    }
    else if (k == "hover" || k == "text" || k == "hovertext")
        HOVER = ClipHover(HoverUnescape(v));
    else if (k == "time" || k == "default_time") DEFAULT_TIME = (float)v;
    else if (k == "attach") ATTACH_POINT = (integer)v;
    else if (k == "public")
    {
        string lv = llToLower(v);
        PUBLIC = !(lv == "0" || lv == "false" || lv == "off" || lv == "no");
    }
    else if (k == "color" || k == "text_color")
        llMessageLinked(LINK_SET, 0xC07E, "EN|set|" + v, NULL_KEY);
}

integer ReadNote()
{
    if (llGetInventoryType(NOTECARD_NAME) != INVENTORY_NOTECARD)
    {
        gNotePending = FALSE;
        return FALSE;
    }
    gNotePending = TRUE;
    gLine = 0;
    gNoteQuery = llGetNotecardLine(NOTECARD_NAME, 0);
    return TRUE;
}

TryAttach()
{
    integer a = llGetAttached();
    if (a)
    {
        if (a >= 31 && a <= 38)
            llOwnerSay("BODY object, not HUD. Wear on Head or Chest.");
        SetupLook();
        return;
    }
    if (!gAttachTried)
    {
        gAttachTried = TRUE;
        llRequestPermissions(llGetOwner(), PERMISSION_ATTACH);
    }
}

default
{
    state_entry()
    {
        // Child prims must not run this (stack-heap). Glass root only.
        if (llGetLinkNumber() > 1)
        {
            llOwnerSay("Controller belongs in Glass (root). Removing this copy.");
            llRemoveInventory(llGetScriptName());
            return;
        }
        gConnected = FALSE;
        gVib = 0;
        gVMax = 20;
        gPump = 0;
        gShowText = FALSE;
        gAttachTried = FALSE;
        gPromptKind = PROMPT_NONE;
        gNotePending = FALSE;
        gUser = NULL_KEY;
        gAim = NULL_KEY;
        gUrl = "";
        gPend = "";
        gUses = LoadUses();
        gPaired = FALSE;
        gCoolAt = -10.0;
        gOrbit = TRUE;
        gNeedsTxt = "";
        gTipTxt = "";
        gEnerTxt = "";
        LoadCfg();
        gShowText = FALSE;
        if (!TokenMissing()) SaveCfg();
        llOwnerSay("Lovense: click = menu. URL to pair. Look + JarHost + Energy in Glass.");
        SetupLook();
        ReadNote();
        TryAttach();
        AskUrl();
    }

    on_rez(integer p)
    {
        gAttachTried = FALSE;
        TryAttach();
        AskUrl();
    }

    attach(key id)
    {
        if (id != NULL_KEY)
        {
            gShowText = FALSE;
            SetupLook();
            AskUrl();
        }
    }

    run_time_permissions(integer perm)
    {
        if (perm & PERMISSION_ATTACH)
        {
            integer point = ATTACH_POINT;
            if (point >= 31 && point <= 38) point = 2;
            if (point < 1 || point > 30) point = 2;
            llAttachToAvatar(point);
        }
    }

    changed(integer change)
    {
        if (change & CHANGED_INVENTORY) ReadNote();
        if (change & CHANGED_OWNER)
        {
            llLinksetDataDelete("lv.ok");
            llLinksetDataDelete("lv.token");
            llLinksetDataDelete("lv.tok");
            llResetScript();
        }
        if (change & (CHANGED_REGION | CHANGED_REGION_START | CHANGED_TELEPORT))
        {
            LoadCfg();
            if (!TokenMissing()) SaveCfg();
            AskUrl();
        }
    }

    touch_start(integer n)
    {
        key who = llDetectedKey(0);
        if (who != llGetOwner() && !PUBLIC)
        {
            llInstantMessage(who, "Owner locked this control.");
            return;
        }
        if (llGetTime() - gCoolAt < 0.6 && who == gUser)
        {
            MenuMain();
            return;
        }
        gCoolAt = llGetTime();
        gUser = who;
        MenuMain();
    }

    link_message(integer sender, integer num, string str, key id)
    {
        if (num != 0xC07E) return;
        if (llGetSubString(str, 0, 8) == "NEEDSTXT|")
        {
            gNeedsTxt = llGetSubString(str, 9, -1);
            Paint();
            return;
        }
        if (llGetSubString(str, 0, 6) == "TIPTXT|")
        {
            gTipTxt = llGetSubString(str, 7, -1);
            Paint();
            return;
        }
        if (llGetSubString(str, 0, 7) == "ENERTXT|")
        {
            gEnerTxt = llGetSubString(str, 8, -1);
            Paint();
            return;
        }
        if (str == "EN|repaint")
        {
            Paint();
            return;
        }
        if (llGetSubString(str, 0, 7) == "TJ|buzz|")
        {
            ApplyBuzz(str, id);
            return;
        }
        ApplyCmd(str);
    }

    dataserver(key id, string data)
    {
        if (id != gNoteQuery) return;
        if (data != EOF)
        {
            CfgLine(data);
            gLine += 1;
            gNoteQuery = llGetNotecardLine(NOTECARD_NAME, gLine);
        }
        else
        {
            gNotePending = FALSE;
            if (!TokenMissing()) SaveCfg();
            Paint();
        }
    }

    listen(integer channel, string name, key id, string msg)
    {
        if (channel != gMenuChan) return;
        if (id != gUser) return;
        if (gPromptKind == PROMPT_TOKEN)
        {
            gPromptKind = PROMPT_NONE;
            msg = llStringTrim(msg, STRING_TRIM);
            if (msg != "")
            {
                TOKEN = msg;
                SaveCfg();
                llOwnerSay("TOKEN saved (kept after sim change).");
            }
            return;
        }
        if (gPromptKind == PROMPT_HOVER)
        {
            gPromptKind = PROMPT_NONE;
            msg = llStringTrim(msg, STRING_TRIM);
            if (msg == "")
            {
                HOVER = "";
                llOwnerSay("Hover reset to default.");
            }
            else
            {
                HOVER = ClipHover(HoverUnescape(msg));
                llOwnerSay("Hover saved.");
            }
            SaveCfg();
            Paint();
            return;
        }
        OnBtn(msg);
    }

    http_request(key id, string method, string body)
    {
        if (method == URL_REQUEST_GRANTED)
        {
            gUrl = body;
            gPaired = FALSE;
            Paint();
            return;
        }
        if (method == URL_REQUEST_DENIED)
        {
            gUrl = "";
            llOwnerSay("SL URL denied — try another sim / reset script.");
            Paint();
            return;
        }
        if (!TokenOk(id, body))
        {
            llHTTPResponse(id, 401, "{\"ok\":false,\"error\":\"unauthorized\"}");
            return;
        }
        method = llToUpper(method);
        if (method == "POST")
        {
            string c = llJsonGetValue(body, ["connected"]);
            gConnected = (llToLower(c) == "true" || c == "1");
            string n = llJsonGetValue(body, ["connected_count"]);
            if (n != JSON_INVALID && ((integer)n) > 0) gConnected = TRUE;
            string vs = llJsonGetValue(body, ["vibrate"]);
            if (vs != JSON_INVALID && vs != "") gVib = (integer)vs;
            if (gVib > 0) gConnected = TRUE;
            string mx = llJsonGetValue(body, ["max_vibrate"]);
            if (mx != JSON_INVALID && mx != "") gVMax = (integer)mx;
            if (gVMax < 1) gVMax = 20;
            string ps = llJsonGetValue(body, ["pump"]);
            if (ps != JSON_INVALID && ps != "") gPump = (integer)ps;
            string es = llJsonGetValue(body, ["energy"]);
            string bk = llJsonGetValue(body, ["bank"]);
            if (es != JSON_INVALID && es != "")
                llMessageLinked(LINK_SET, 0xC07E, "EN|pc|" + es + "|" + bk, NULL_KEY);
            gPaired = TRUE;
            Paint();
            PulseNeeds("vibe");
            llHTTPResponse(id, 200, "{\"ok\":true}");
            return;
        }
        // GET — PC is talking to us
        gPaired = TRUE;
        string pend;
        string q = llLinksetDataRead("lv.bank");
        if (q != "" && gPend != "clearbank")
        {
            pend = "{\"action\":\"bank\",\"q\":\"" + JsonEsc(q) + "\"}";
            llLinksetDataWrite("lv.bank", "");
            llLinksetDataWrite("lv.bankn", "0");
            llMessageLinked(LINK_SET, 0xC07E, "EN|flush", NULL_KEY);
        }
        else
        {
            pend = PendJson();
            gPend = "";
        }
        llHTTPResponse(id, 200,
            "{\"ok\":true,\"service\":\"lovense-sl\",\"pending\":" + pend + "}");
    }
}
