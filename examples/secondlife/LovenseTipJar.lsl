// Lovense tip jar — ground vessel. Pay L$ to buzz the toy.
// Does not change prim shape, size, color, or position.
// Rez this on the floor. Wear is not supported (Pay on attachments is unreliable).
//
// Needs the paired Lovense orb (LovenseController.lsl) in the SAME region.
// Owner menu: type /77 jar   (left click is Pay while the jar is open).
// Optional notecard name: tipjar.cfg

integer OPEN = TRUE;
integer SHOW_TEXT = TRUE;
string  TITLE = "Tip jar";
string  THANKS = "Thanks {name}! L${amount} -> {time}s";
integer PRICE_A = 10;
integer PRICE_B = 50;
integer PRICE_C = 100;
integer PRICE_D = 250;
integer PRICE_OTHER = 25;
integer OWNER_CHAN = 77;

string  NOTECARD_NAME = "tipjar.cfg";

integer PROMPT_NONE  = 0;
integer PROMPT_TITLE = 1;
integer PROMPT_THANKS = 2;

integer gMenuChan;
integer gMenuListen;
integer gOwnListen;
integer gCmdListen;
integer gPromptKind;
integer gOpen;
integer gShow;
integer gSessionL;
integer gSessionN;
integer gLastL;
string  gLastName;
integer gNoteLine;
key     gNoteQuery;
integer gNotePending;
integer gOrbHeard;

// Highest matching tier wins. kind: i=intensity 0-1, v=level 0-20, p=preset
list TIER_L    = [1,  10,  25,  50,  100, 250, 500];
list TIER_KIND = ["i","i","i","i","i","p","p"];
list TIER_VAL  = ["0.15","0.28","0.42","0.58","0.78","pulse","fireworks"];
list TIER_SEC  = ["4","6","8","12","18","20","28"];

integer CmdChan()
{
    return 0xC07E1000 ^ (integer)("0x" + llGetSubString((string)llGetOwner(), 0, 7));
}

integer OnGround()
{
    return (llGetAttached() == 0);
}

string Clip(string s, integer n)
{
    if (llStringLength(s) > n) return llGetSubString(s, 0, n - 1);
    return s;
}

HelloOrb()
{
    llRegionSay(CmdChan(), "TJ|hello");
}

PushTip()
{
    string t = "";
    if (gSessionL > 0 || gSessionN > 0)
    {
        t = "tips L$" + (string)gSessionL;
        if (gSessionN > 0) t += "  x" + (string)gSessionN;
    }
    llRegionSay(CmdChan(), "TIPTXT|" + t);
}

string Replace(string s, string a, string b)
{
    integer p = llSubStringIndex(s, a);
    while (p >= 0)
    {
        s = llGetSubString(s, 0, p - 1) + b + llGetSubString(s, p + llStringLength(a), -1);
        p = llSubStringIndex(s, a);
    }
    return s;
}

integer LoadSaved()
{
    if (llLinksetDataRead("tj.ok") != "1") return FALSE;
    string t = llLinksetDataRead("tj.title");
    if (t != "") TITLE = t;
    string th = llLinksetDataRead("tj.thanks");
    if (th != "") THANKS = th;
    string o = llLinksetDataRead("tj.open");
    if (o != "") gOpen = (integer)o;
    string sh = llLinksetDataRead("tj.show");
    if (sh != "") gShow = (integer)sh;
    string sl = llLinksetDataRead("tj.sessionL");
    if (sl != "") gSessionL = (integer)sl;
    string sn = llLinksetDataRead("tj.sessionN");
    if (sn != "") gSessionN = (integer)sn;
    return TRUE;
}

SaveSaved()
{
    llLinksetDataWrite("tj.ok", "1");
    llLinksetDataWrite("tj.title", TITLE);
    llLinksetDataWrite("tj.thanks", THANKS);
    llLinksetDataWrite("tj.open", (string)gOpen);
    llLinksetDataWrite("tj.show", (string)gShow);
    llLinksetDataWrite("tj.sessionL", (string)gSessionL);
    llLinksetDataWrite("tj.sessionN", (string)gSessionN);
}

SendCmd(string payload, key who)
{
    string buzz = "TJ|buzz|" + payload + "|" + (string)who;
    llRegionSay(CmdChan(), buzz);
    llRegionSay(CmdChan(), "LVQ|" + payload);
}

integer PickTier(integer amount)
{
    integer i;
    integer n = llGetListLength(TIER_L);
    integer best = 0;
    for (i = 0; i < n; i += 1)
    {
        if (amount >= llList2Integer(TIER_L, i))
            best = i;
    }
    return best;
}

string KindOf(integer i) { return llList2String(TIER_KIND, i); }
string ValOf(integer i)  { return llList2String(TIER_VAL, i); }
string SecOf(integer i)  { return llList2String(TIER_SEC, i); }

string FmtThanks(key who, integer amount, integer tier)
{
    string s = THANKS;
    s = Replace(s, "{name}", llGetDisplayName(who));
    s = Replace(s, "{amount}", (string)amount);
    s = Replace(s, "{level}", ValOf(tier));
    s = Replace(s, "{time}", SecOf(tier));
    s = Replace(s, "{total}", (string)gSessionL);
    return Clip(s, 200);
}

SetPay()
{
    if (!OnGround())
    {
        llSetPayPrice(PAY_HIDE, [PAY_HIDE, PAY_HIDE, PAY_HIDE, PAY_HIDE]);
        llSetClickAction(CLICK_ACTION_TOUCH);
        llSetLinkPrimitiveParamsFast(LINK_SET, [PRIM_CLICK_ACTION, CLICK_ACTION_TOUCH]);
        return;
    }
    if (!gOpen)
        llSetPayPrice(PAY_HIDE, [PAY_HIDE, PAY_HIDE, PAY_HIDE, PAY_HIDE]);
    else
        llSetPayPrice(PRICE_OTHER, [PRICE_A, PRICE_B, PRICE_C, PRICE_D]);
    integer action = CLICK_ACTION_TOUCH;
    if (gOpen) action = CLICK_ACTION_PAY;
    llSetClickAction(action);
    llSetLinkPrimitiveParamsFast(LINK_SET, [PRIM_CLICK_ACTION, action]);
}

Paint()
{
    if (!gShow)
    {
        llSetText("", ZERO_VECTOR, 0.0);
        return;
    }
    vector tc = <1.00, 0.82, 0.90>;
    string line;
    if (!OnGround())
    {
        llSetText(Clip(TITLE + "\nrez on the ground", 240), <1.00, 0.70, 0.50>, 1.0);
        return;
    }
    if (!gOpen)
    {
        llSetText(Clip(TITLE + "\nclosed", 240), <1.00, 0.70, 0.50>, 1.0);
        return;
    }
    line = "✦  " + TITLE;
    line += "\nL$" + (string)PRICE_A + "  tease";
    line += "\nL$" + (string)PRICE_B + "  medium";
    line += "\nL$" + (string)PRICE_C + "  hard";
    line += "\nL$" + (string)PRICE_D + "  pulse";
    if (gLastName != "")
        line += "\nlast: " + Clip(gLastName, 18) + "  L$" + (string)gLastL;
    line += "\nsession L$" + (string)gSessionL + "  x" + (string)gSessionN;
    if (!gOrbHeard)
        line += "\nwaiting for orb";
    llSetText(Clip(line, 240), tc, 1.0);
}

OpenListen(key who)
{
    gMenuChan = 0x80000000 | (integer)llFrand(0x7FFFFFFF);
    llListenRemove(gMenuListen);
    gMenuListen = llListen(gMenuChan, "", who, "");
}

OwnerMenu()
{
    gPromptKind = PROMPT_NONE;
    OpenListen(llGetOwner());
    string st = "open";
    if (!gOpen) st = "closed";
    string orb = "orb ok";
    if (!gOrbHeard) orb = "no orb";
    llDialog(llGetOwner(),
        "Tip jar [" + st + "]  " + orb
            + "\nsession L$" + (string)gSessionL
            + "  x" + (string)gSessionN
            + "\nLeft click = Pay. Menu: /77 jar",
        ["Close", "Open", "Reset $", "Show text",
         "Hide text", "Test 50", "Title", "Thanks",
         "Help", "Ping orb", "-", "-"],
        gMenuChan);
}

Help()
{
    llOwnerSay("Rez this vessel on the ground. Wear the Lovense orb in this region.");
    llOwnerSay("Left click = Pay. Owner menu: type /77 jar");
    llOwnerSay("Script does not change the mesh. Optional notecard: tipjar.cfg");
}

DoTip(key who, integer amount)
{
    if (amount < 1) return;
    if (!gOpen && who != llGetOwner())
    {
        llInstantMessage(who, "Tip jar is closed.");
        return;
    }
    integer tier = PickTier(amount);
    string kind = KindOf(tier);
    string val = ValOf(tier);
    string sec = SecOf(tier);
    gSessionL += amount;
    gSessionN += 1;
    gLastL = amount;
    gLastName = llGetDisplayName(who);
    SaveSaved();
    SendCmd(kind + "|" + val + "|" + sec, who);
    Paint();
    PushTip();
    string th = FmtThanks(who, amount, tier);
    if (who != llGetOwner())
        llInstantMessage(who, th);
    llOwnerSay("Tip L$" + (string)amount + " from " + gLastName
        + " -> " + kind + " " + val + " " + sec + "s");
    if (!gOrbHeard)
        llOwnerSay("Orb not heard in this region — wear the paired ball and wait a few seconds.");
}

HandleCmd(string str, key id)
{
    if (str == "TJ|pong")
    {
        gOrbHeard = TRUE;
        Paint();
        return;
    }
    if (str == "TJ|open")
    {
        gOpen = TRUE;
        SaveSaved();
        SetPay();
        Paint();
        llOwnerSay("Tip jar open.");
        return;
    }
    if (str == "TJ|close")
    {
        gOpen = FALSE;
        SaveSaved();
        SetPay();
        Paint();
        llOwnerSay("Tip jar closed.");
        return;
    }
    if (str == "TJ|reset")
    {
        gSessionL = 0;
        gSessionN = 0;
        gLastL = 0;
        gLastName = "";
        SaveSaved();
        Paint();
        PushTip();
        llOwnerSay("Tip session reset.");
        return;
    }
    if (str == "TJ|test50")
    {
        DoTip(llGetOwner(), 50);
        return;
    }
    if (str == "TJ|die")
    {
        if (OnGround()) llDie();
        return;
    }
}

CfgLine(string line)
{
    line = llStringTrim(line, STRING_TRIM);
    if (line == "" || llGetSubString(line, 0, 0) == "#") return;
    integer eq = llSubStringIndex(line, "=");
    if (eq < 1) return;
    string k = llToLower(llStringTrim(llGetSubString(line, 0, eq - 1), STRING_TRIM));
    string v = llStringTrim(llGetSubString(line, eq + 1, -1), STRING_TRIM);
    if (k == "title" || k == "hover") TITLE = Clip(v, 40);
    else if (k == "thanks") THANKS = v;
    else if (k == "open")
    {
        string lv = llToLower(v);
        gOpen = !(lv == "0" || lv == "false" || lv == "off" || lv == "no");
    }
    else if (k == "show" || k == "show_text")
    {
        string lv = llToLower(v);
        gShow = !(lv == "0" || lv == "false" || lv == "off" || lv == "no");
    }
    else if (k == "price_a" || k == "price1") PRICE_A = (integer)v;
    else if (k == "price_b" || k == "price2") PRICE_B = (integer)v;
    else if (k == "price_c" || k == "price3") PRICE_C = (integer)v;
    else if (k == "price_d" || k == "price4") PRICE_D = (integer)v;
    else if (k == "price_other" || k == "price") PRICE_OTHER = (integer)v;
}

integer ReadNote()
{
    if (llGetInventoryType(NOTECARD_NAME) != INVENTORY_NOTECARD)
    {
        gNotePending = FALSE;
        return FALSE;
    }
    gNotePending = TRUE;
    gNoteLine = 0;
    gNoteQuery = llGetNotecardLine(NOTECARD_NAME, 0);
    return TRUE;
}

Boot()
{
    gOpen = OPEN;
    gShow = SHOW_TEXT;
    gPromptKind = PROMPT_NONE;
    gSessionL = 0;
    gSessionN = 0;
    gLastL = 0;
    gLastName = "";
    gOrbHeard = FALSE;
    LoadSaved();
    llListenRemove(gCmdListen);
    gCmdListen = llListen(CmdChan(), "", NULL_KEY, "");
    llListenRemove(gOwnListen);
    gOwnListen = llListen(OWNER_CHAN, "", llGetOwner(), "");
    ReadNote();
    HelloOrb();
    SetPay();
    Paint();
    if (!OnGround())
        llOwnerSay("Tip jar is a ground object. Take it off and rez it on the floor.");
    else
        llOwnerSay("Tip jar on the ground. Left click = Pay. Owner menu: /77 jar");
    llSetTimerEvent(8.0);
}

default
{
    state_entry()
    {
        Boot();
    }

    timer()
    {
        HelloOrb();
        Paint();
        if (gOrbHeard) llSetTimerEvent(40.0);
        else llSetTimerEvent(8.0);
    }

    on_rez(integer p)
    {
        gOrbHeard = FALSE;
        HelloOrb();
        SetPay();
        Paint();
        llSetTimerEvent(8.0);
    }

    attach(key id)
    {
        gOrbHeard = FALSE;
        SetPay();
        Paint();
        if (id != NULL_KEY)
            llOwnerSay("Tip jar is a ground object. Detach and rez it on the floor.");
    }

    changed(integer change)
    {
        if (change & CHANGED_INVENTORY) ReadNote();
        if (change & CHANGED_OWNER)
        {
            llLinksetDataDelete("tj.ok");
            llResetScript();
        }
        if (change & (CHANGED_REGION | CHANGED_REGION_START | CHANGED_TELEPORT))
        {
            gOrbHeard = FALSE;
            HelloOrb();
            SetPay();
            Paint();
        }
    }

    money(key who, integer amount)
    {
        DoTip(who, amount);
    }

    touch_start(integer n)
    {
        key who = llDetectedKey(0);
        if (who == llGetOwner())
        {
            OwnerMenu();
            return;
        }
        if (!OnGround())
        {
            llInstantMessage(who, "This tip jar belongs on the ground.");
            return;
        }
        if (!gOpen)
            llInstantMessage(who, "Tip jar is closed.");
        else
            llInstantMessage(who, "Use Pay on this jar. L$"
                + (string)PRICE_A + " / " + (string)PRICE_B + " / "
                + (string)PRICE_C + " / " + (string)PRICE_D);
    }

    dataserver(key id, string data)
    {
        if (id != gNoteQuery) return;
        if (data != EOF)
        {
            CfgLine(data);
            gNoteLine += 1;
            gNoteQuery = llGetNotecardLine(NOTECARD_NAME, gNoteLine);
        }
        else
        {
            gNotePending = FALSE;
            SaveSaved();
            SetPay();
            Paint();
        }
    }

    listen(integer channel, string name, key id, string msg)
    {
        if (channel == CmdChan())
        {
            if (llGetAgentSize(id) != ZERO_VECTOR) return;
            if (llGetOwnerKey(id) != llGetOwner()) return;
            HandleCmd(msg, id);
            return;
        }
        if (channel == OWNER_CHAN)
        {
            msg = llToLower(llStringTrim(msg, STRING_TRIM));
            if (msg == "jar" || msg == "menu" || msg == "tip")
                OwnerMenu();
            return;
        }
        if (channel != gMenuChan) return;
        if (id != llGetOwner()) return;
        if (gPromptKind == PROMPT_TITLE)
        {
            gPromptKind = PROMPT_NONE;
            msg = llStringTrim(msg, STRING_TRIM);
            if (msg != "") TITLE = Clip(msg, 40);
            SaveSaved();
            Paint();
            llOwnerSay("Title saved.");
            return;
        }
        if (gPromptKind == PROMPT_THANKS)
        {
            gPromptKind = PROMPT_NONE;
            msg = llStringTrim(msg, STRING_TRIM);
            if (msg != "") THANKS = msg;
            SaveSaved();
            llOwnerSay("Thanks text saved.");
            return;
        }
        if (msg == "-" || msg == " " ) return;
        if (msg == "Close")
        {
            gOpen = FALSE;
            SaveSaved();
            SetPay();
            Paint();
            llOwnerSay("Closed — Pay hidden. Click the jar for this menu.");
            return;
        }
        if (msg == "Open")
        {
            gOpen = TRUE;
            SaveSaved();
            SetPay();
            Paint();
            llOwnerSay("Open for tips. Left click = Pay. Menu: /77 jar");
            return;
        }
        if (msg == "Reset $")
        {
            gSessionL = 0;
            gSessionN = 0;
            gLastL = 0;
            gLastName = "";
            SaveSaved();
            Paint();
            PushTip();
            llOwnerSay("Session totals reset.");
            return;
        }
        if (msg == "Show text") { gShow = TRUE; SaveSaved(); Paint(); return; }
        if (msg == "Hide text") { gShow = FALSE; SaveSaved(); Paint(); return; }
        if (msg == "Test 50")
        {
            DoTip(llGetOwner(), 50);
            return;
        }
        if (msg == "Ping orb")
        {
            gOrbHeard = FALSE;
            HelloOrb();
            Paint();
            llOwnerSay("Pinged the orb.");
            return;
        }
        if (msg == "Title")
        {
            OpenListen(llGetOwner());
            gPromptKind = PROMPT_TITLE;
            llTextBox(llGetOwner(), "Hover title. Now: " + TITLE, gMenuChan);
            return;
        }
        if (msg == "Thanks")
        {
            OpenListen(llGetOwner());
            gPromptKind = PROMPT_THANKS;
            llTextBox(llGetOwner(),
                "Thanks IM. Tokens: {name} {amount} {level} {time} {total}\nNow: " + THANKS,
                gMenuChan);
            return;
        }
        if (msg == "Help") Help();
    }
}
