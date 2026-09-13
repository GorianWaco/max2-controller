// Lovense Needs: meters over the avatar head.
// Second script in the SAME sphere as LovenseController.lsl.

float gHugRange = 1.5;
float gSocialRange = 20.0;
float gTick = 2.0;
float gHornyBump = 10.0;
float gHornyPerMin = 12.0;
float gHornyDecay = 1.5;
float gHygDrain = 0.8;
float gHygRecover = 0.35;
float gHygWash = 80.0;
float gHugsPerMin = 14.0;
float gHugsDecay = 2.5;
float gSocialPer = 3.0;
float gSocialDecay = 4.0;
integer gDirtyHold = 300;

float gHorny;
float gHygiene;
float gHugs;
float gSocial;
integer gVib;
integer gVMax;
integer gLastVibeUnix;
integer gNear;
integer gHugHere;
integer gInWater;
integer gPaused;
integer gShow;
integer gMenuChan;
integer gMenuListen;
integer gListen;
integer gNoteLine;
key gNoteQuery;
integer gDirtySave;

integer NeedsChan()
{
    return 0xC07E0000 ^ (integer)("0x" + llGetSubString((string)llGetOwner(), 0, 7));
}

float Clamp100(float x)
{
    if (x < 0.0) return 0.0;
    if (x > 100.0) return 100.0;
    return x;
}

string Bar(float x)
{
    integer filled;
    integer k;
    string s;
    filled = (integer)(x / 10.0 + 0.5);
    if (filled < 0) filled = 0;
    if (filled > 10) filled = 10;
    s = "";
    for (k = 0; k < 10; k += 1)
    {
        if (k < filled) s += "●";
        else s += "○";
    }
    return s;
}

string Pct(float x)
{
    integer n;
    n = (integer)(x + 0.5);
    return (string)n;
}

SaveNeeds()
{
    llLinksetDataWrite("ln.ok", "1");
    llLinksetDataWrite("ln.horny", (string)gHorny);
    llLinksetDataWrite("ln.hygiene", (string)gHygiene);
    llLinksetDataWrite("ln.hugs", (string)gHugs);
    llLinksetDataWrite("ln.social", (string)gSocial);
    llLinksetDataWrite("ln.show", (string)gShow);
    llLinksetDataWrite("ln.pause", (string)gPaused);
    llLinksetDataWrite("ln.vibeunix", (string)gLastVibeUnix);
}

LoadNeeds()
{
    if (llLinksetDataRead("ln.ok") != "1")
    {
        gHorny = 8.0;
        gHygiene = 100.0;
        gHugs = 22.0;
        gSocial = 22.0;
        gShow = TRUE;
        gPaused = FALSE;
        gLastVibeUnix = 0;
        SaveNeeds();
        return;
    }
    gHorny = (float)llLinksetDataRead("ln.horny");
    gHygiene = (float)llLinksetDataRead("ln.hygiene");
    gHugs = (float)llLinksetDataRead("ln.hugs");
    gSocial = (float)llLinksetDataRead("ln.social");
    gShow = (integer)llLinksetDataRead("ln.show");
    if (llLinksetDataRead("ln.show") == "") gShow = TRUE;
    gPaused = (integer)llLinksetDataRead("ln.pause");
    gLastVibeUnix = (integer)llLinksetDataRead("ln.vibeunix");
}

Paint()
{
    string t;
    if (!gShow)
    {
        llMessageLinked(LINK_SET, 0xC07E, "NEEDSTXT|", NULL_KEY);
        return;
    }
    t = "Horny    " + Bar(gHorny) + "  " + Pct(gHorny);
    t += "\nHygiene  " + Bar(gHygiene) + "  " + Pct(gHygiene);
    t += "\nHugs     " + Bar(gHugs) + "  " + Pct(gHugs);
    t += "\nSocial   " + Bar(gSocial) + "  " + Pct(gSocial);
    if (gInWater) t += "\nwashing";
    if (gNear > 0) t += "\n" + (string)gNear + " nearby";
    if (gPaused) t += "\npaused";
    llMessageLinked(LINK_SET, 0xC07E, "NEEDSTXT|" + t, NULL_KEY);
}

StartSense()
{
    llSensorRemove();
    llSensorRepeat("", NULL_KEY, AGENT, gSocialRange, PI, gTick);
}

integer InWater()
{
    // Linden water plane (ocean / sim pond). Prim pools do not count.
    key who = llGetOwner();
    vector sz = llGetAgentSize(who);
    if (sz.z < 0.1) return FALSE;
    vector av = llList2Vector(llGetObjectDetails(who, [OBJECT_POS]), 0);
    float water = llWater(ZERO_VECTOR);
    float feet = av.z - (sz.z * 0.5);
    if (feet <= water) return TRUE;
    if (av.z <= water) return TRUE;
    string anim = llToLower(llGetAnimation(who));
    if (llSubStringIndex(anim, "swim") >= 0) return TRUE;
    return FALSE;
}

Tick()
{
    float dtm;
    integer now;
    integer vmax;
    float x;
    integer dirty;
    if (gPaused)
    {
        Paint();
        return;
    }
    dtm = gTick / 60.0;
    now = llGetUnixTime();
    vmax = gVMax;
    if (vmax < 1) vmax = 20;
    x = 0.0;
    if (gVib > 0) x = (float)gVib / (float)vmax;
    if (x > 1.0) x = 1.0;
    if (x > 0.0)
    {
        gHorny += gHornyPerMin * x * dtm;
        gLastVibeUnix = now;
    }
    else
        gHorny -= gHornyDecay * dtm;
    dirty = FALSE;
    if (x > 0.0) dirty = TRUE;
    if (gLastVibeUnix > 0)
    {
        if ((now - gLastVibeUnix) < gDirtyHold) dirty = TRUE;
    }
    gInWater = InWater();
    if (gInWater)
    {
        gLastVibeUnix = 0;
        gHygiene += gHygWash * dtm;
    }
    else if (dirty) gHygiene -= gHygDrain * dtm;
    else gHygiene += gHygRecover * dtm;
    if (gHugHere) gHugs += gHugsPerMin * dtm;
    else gHugs -= gHugsDecay * dtm;
    if (gNear > 0) gSocial += gSocialPer * (float)gNear * dtm;
    else gSocial -= gSocialDecay * dtm;
    gHorny = Clamp100(gHorny);
    gHygiene = Clamp100(gHygiene);
    gHugs = Clamp100(gHugs);
    gSocial = Clamp100(gSocial);
    gDirtySave = TRUE;
    Paint();
}

HandlePulse(string msg)
{
    list p;
    string kind;
    p = llParseString2List(msg, ["|"], []);
    if (llList2String(p, 0) != "LV") return;
    kind = llList2String(p, 1);
    gVib = (integer)llList2String(p, 2);
    gVMax = (integer)llList2String(p, 3);
    if (gVMax < 1) gVMax = 20;
    if (kind == "queue")
    {
        if (!gPaused)
        {
            gHorny = Clamp100(gHorny + gHornyBump);
            gLastVibeUnix = llGetUnixTime();
            SaveNeeds();
            Paint();
        }
    }
    else if (kind == "stop")
    {
        gVib = 0;
        Paint();
    }
}

CfgLine(string line)
{
    integer eq;
    string k;
    float v;
    line = llStringTrim(line, STRING_TRIM);
    if (line == "") return;
    if (llGetSubString(line, 0, 0) == "#") return;
    eq = llSubStringIndex(line, "=");
    if (eq < 1) return;
    k = llToLower(llStringTrim(llGetSubString(line, 0, eq - 1), STRING_TRIM));
    v = (float)llStringTrim(llGetSubString(line, eq + 1, -1), STRING_TRIM);
    if (k == "hug_range") gHugRange = v;
    else if (k == "social_range") gSocialRange = v;
    else if (k == "horny_queue") gHornyBump = v;
    else if (k == "horny_per_min") gHornyPerMin = v;
    else if (k == "hygiene_drain") gHygDrain = v;
    else if (k == "hygiene_wash") gHygWash = v;
    else if (k == "hugs_per_min") gHugsPerMin = v;
    else if (k == "social_per_person") gSocialPer = v;
}

ReadNote()
{
    if (llGetInventoryType("needs.cfg") != INVENTORY_NOTECARD) return;
    gNoteLine = 0;
    gNoteQuery = llGetNotecardLine("needs.cfg", 0);
}

Menu()
{
    string p;
    string vis;
    gMenuChan = 0x80000000 | (integer)llFrand(0x7FFFFFFF);
    llListenRemove(gMenuListen);
    gMenuListen = llListen(gMenuChan, "", llGetOwner(), "");
    p = "Pause";
    if (gPaused) p = "Resume";
    vis = "Hide";
    if (!gShow) vis = "Show";
    llDialog(llGetOwner(),
        "Needs  H" + Pct(gHorny) + "  Y" + Pct(gHygiene)
        + "  U" + Pct(gHugs) + "  S" + Pct(gSocial),
        [p, vis, "Reset", "Help"], gMenuChan);
}

default
{
    state_entry()
    {
        gVib = 0;
        gVMax = 20;
        gNear = 0;
        gHugHere = FALSE;
        gInWater = FALSE;
        gDirtySave = FALSE;
        LoadNeeds();
        Paint();
        ReadNote();
        llListenRemove(gListen);
        gListen = llListen(NeedsChan(), "", NULL_KEY, "");
        StartSense();
        llSetTimerEvent(gTick);
        llOwnerSay("Needs over head. Second script in the Lovense sphere.");
    }

    on_rez(integer p)
    {
        LoadNeeds();
        Paint();
        StartSense();
    }

    attach(key id)
    {
        if (id != NULL_KEY)
        {
            LoadNeeds();
            Paint();
            StartSense();
            llListenRemove(gListen);
            gListen = llListen(NeedsChan(), "", NULL_KEY, "");
        }
        else
            SaveNeeds();
    }

    changed(integer change)
    {
        if (change & CHANGED_INVENTORY) ReadNote();
        if (change & CHANGED_OWNER)
        {
            llLinksetDataDelete("ln.ok");
            llResetScript();
        }
        if (change & (CHANGED_REGION | CHANGED_REGION_START | CHANGED_TELEPORT))
        {
            SaveNeeds();
            StartSense();
            llListenRemove(gListen);
            gListen = llListen(NeedsChan(), "", NULL_KEY, "");
        }
    }

    timer()
    {
        Tick();
        if (gDirtySave)
        {
            SaveNeeds();
            gDirtySave = FALSE;
        }
    }

    sensor(integer num)
    {
        integer k;
        integer nnear;
        integer nclose;
        key owner;
        owner = llGetOwner();
        nnear = 0;
        nclose = 0;
        for (k = 0; k < num; k += 1)
        {
            if (llDetectedKey(k) != owner)
            {
                nnear += 1;
                if (llVecDist(llGetPos(), llDetectedPos(k)) <= gHugRange)
                    nclose = 1;
            }
        }
        gNear = nnear;
        gHugHere = nclose;
    }

    no_sensor()
    {
        gNear = 0;
        gHugHere = FALSE;
    }

    listen(integer channel, string name, key id, string msg)
    {
        if (channel == NeedsChan())
        {
            HandlePulse(msg);
            return;
        }
        if (channel != gMenuChan) return;
        if (id != llGetOwner()) return;
        if (msg == "Pause")
        {
            gPaused = TRUE;
            SaveNeeds();
            Paint();
            return;
        }
        if (msg == "Resume")
        {
            gPaused = FALSE;
            SaveNeeds();
            Paint();
            return;
        }
        if (msg == "Hide")
        {
            gShow = FALSE;
            SaveNeeds();
            Paint();
            return;
        }
        if (msg == "Show")
        {
            gShow = TRUE;
            SaveNeeds();
            Paint();
            return;
        }
        if (msg == "Reset")
        {
            gHorny = 8.0;
            gHygiene = 100.0;
            gHugs = 22.0;
            gSocial = 22.0;
            gLastVibeUnix = 0;
            SaveNeeds();
            Paint();
            llOwnerSay("Needs reset.");
            return;
        }
        if (msg == "Help")
        {
            llOwnerSay("Horny rises when someone starts the toy and while it vibrates.");
            llOwnerSay("Hygiene drops slowly after vibration. Walk into Linden water to wash.");
            llOwnerSay("Hugs rise if someone is very close. Social fills with avatars in 20 m.");
        }
    }

    link_message(integer sender, integer num, string str, key id)
    {
        if (num != 0xC07E) return;
        if (str == "NEEDSMENU")
        {
            Menu();
            return;
        }
        if (str == "NEEDSHIDE")
        {
            gShow = FALSE;
            Paint();
            return;
        }
        if (str == "NEEDSSHOW")
        {
            gShow = TRUE;
            Paint();
            return;
        }
        HandlePulse(str);
    }

    touch_start(integer n)
    {
        if (llDetectedKey(0) != llGetOwner()) return;
        if (llGetInventoryNumber(INVENTORY_SCRIPT) > 1) return;
        Menu();
    }

    dataserver(key qid, string data)
    {
        if (qid != gNoteQuery) return;
        if (data != EOF)
        {
            CfgLine(data);
            gNoteLine += 1;
            gNoteQuery = llGetNotecardLine("needs.cfg", gNoteLine);
        }
        else
            StartSense();
    }
}
