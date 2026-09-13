// Lovense LOOK — particles, glow, light, surface sliding.
// Second script in the Glass ROOT only. No HTTP. No menus.
// Per-child radius, size, and heartbeat tempo.
// Controller sends: LOOK|fx|vib|vmax|connected|paired|aimKey
//                   LOOK|orbit|0   LOOK|orbit|1

// --- GENERAL ---
float   SURFACE_SPEED = 0.02;        // How fast the beads slide around the surface
float   BASE_RADIUS = 0.025;         // Base distance from center
float   HEARTBEAT_SPEED = 0.5;       // Base pulse rate
float   HEARTBEAT_INTENSITY = 1.2;   // Beat strength (1.2 = 20% larger at peak)

// --- PER-CHILD ---
// Distance multiplier
list    LIST_DISTANCE_MODIFIERS = [1.1, 1.11, 1.12, 1.122, 1.08, 1.4, 1.45, 1.50, 1.0, 1.0, 1.0, 1.0];

// Size multiplier
list    LIST_SIZE_MODIFIERS =     [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0];

// Heartbeat tempo multiplier (1.0 = default, 1.5 = fast, 0.5 = slow)
list    LIST_BEAT_MODIFIERS =     [1.0, 1.2, 0.8, 1.5, 0.9, 1.3, 1.1, 0.7, 1.0, 1.0, 1.0, 1.0];
// -----------------------------------------------

integer gVib;
integer gVMax;
integer gConnected;
integer gPaired;
integer gFxBand;
integer gOrbit;
integer gOrbitWarned;
float   gPartAt;
key     gAim;
key     gFxAim;

list    gRestSize;

float VibeX()
{
    integer vmax = gVMax;
    if (vmax < 1) vmax = 20;
    float x = 0.0;
    if (gConnected && gVib > 0) x = (float)gVib / (float)vmax;
    if (x > 1.0) x = 1.0;
    return x;
}

integer PrimIsMesh()
{
    list t = llGetPrimitiveParams([PRIM_TYPE]);
    return llList2Integer(t, 0) == PRIM_TYPE_SCULPT;
}

EnsureOrb()
{
    list t = llGetPrimitiveParams([PRIM_TYPE]);
    integer kind = llList2Integer(t, 0);
    if (kind == PRIM_TYPE_BOX)
    {
        llSetObjectName("Lovense");
        llSetPrimitiveParams([
            PRIM_TYPE, PRIM_TYPE_SPHERE, 0, <0.0, 1.0, 0.0>, 0.0,
                ZERO_VECTOR, <0.0, 1.0, 0.0>,
            PRIM_SIZE, <0.12, 0.12, 0.12>,
            PRIM_COLOR, ALL_SIDES, <1.00, 0.34, 0.62>, 0.90,
            PRIM_FULLBRIGHT, ALL_SIDES, TRUE
        ]);
    }
    if (llGetAttached() && kind != PRIM_TYPE_SCULPT)
    {
        vector p = llGetLocalPos();
        if (llVecMag(p) < 0.05)
            llSetPos(<0.0, 0.0, 0.22>);
    }
}

string PickTex()
{
    // Contents textures named p_*  (p_glow, p_star, …). Skip orb/lovense skins.
    integer n = llGetInventoryNumber(INVENTORY_TEXTURE);
    integer i;
    integer hits;
    string last;
    for (i = 0; i < n; ++i)
    {
        string nm = llGetInventoryName(INVENTORY_TEXTURE, i);
        if (llToLower(llGetSubString(nm, 0, 1)) != "p_") jump nxt;
        hits += 1;
        if (llFrand(1.0) < (1.0 / (float)hits)) last = nm;
        @nxt;
    }
    return last;
}

Fx()
{
    float x = VibeX();
    integer band;
    if (x > 0.02)
    {
        if (x < 0.25) band = 1;
        else if (x < 0.50) band = 2;
        else if (x < 0.75) band = 3;
        else band = 4;
    }
    else if (gPaired && gConnected) band = 0;
    else band = -1;
    integer home = FALSE;
    if (gAim != NULL_KEY && llGetAgentSize(gAim) != ZERO_VECTOR) home = TRUE;
    if (band == gFxBand && gAim == gFxAim) return;
    gFxBand = band;
    gFxAim = gAim;

    float glow = 0.05;
    float lit = 0.0;
    integer lamp = FALSE;
    if (band >= 1)
    {
        float t = (float)band / 4.0;
        glow = 0.18 + t * 0.55;
        lit = 0.40 + t * 0.55;
        lamp = TRUE;
        integer count = 2 + band * 2;
        float speed = 0.10 + t * 0.50;
        float speed0 = 0.08;
        float endsc = 0.06 + t * 0.10;
        float age = 0.9 + t * 0.8;
        vector acc = <0.0, 0.0, 0.12 + t * 0.25>;
        integer flags = PSYS_PART_EMISSIVE_MASK |
            PSYS_PART_INTERP_COLOR_MASK |
            PSYS_PART_INTERP_SCALE_MASK |
            PSYS_PART_FOLLOW_VELOCITY_MASK;
        if (home)
        {
            flags = flags | PSYS_PART_TARGET_POS_MASK;
            speed = 0.4 + t * 1.2;
            speed0 = 0.3;
            endsc = 0.08 + t * 0.10;
            count = 4 + band * 3;
            age = 8.6 + t * 4.4;
            acc = <0.06, 0.04, 0.05>;
        }
        else
            flags = flags | PSYS_PART_FOLLOW_SRC_MASK;
        string ptex = PickTex();
        list ps = [
            PSYS_PART_FLAGS, flags,
            PSYS_SRC_PATTERN, PSYS_SRC_PATTERN_EXPLODE,
            PSYS_PART_START_COLOR, <1.00, 0.42, 0.72>,
            PSYS_PART_END_COLOR, <1.00, 0.95, 1.00>,
            PSYS_PART_START_ALPHA, 0.95,
            PSYS_PART_END_ALPHA, 0.0,
            PSYS_PART_START_SCALE, <0.04, 0.04, 0.0>,
            PSYS_PART_END_SCALE, <endsc, endsc, 0.0>,
            PSYS_PART_MAX_AGE, age,
            PSYS_SRC_BURST_RATE, 0.08,
            PSYS_SRC_BURST_PART_COUNT, count,
            PSYS_SRC_BURST_RADIUS, 0.02,
            PSYS_SRC_BURST_SPEED_MIN, speed0,
            PSYS_SRC_BURST_SPEED_MAX, speed,
            PSYS_SRC_ACCEL, acc,
            PSYS_SRC_MAX_AGE, 0.0
        ];
        if (home) ps += [PSYS_SRC_TARGET_KEY, gAim];
        if (ptex != "") ps += [PSYS_SRC_TEXTURE, ptex];
        llParticleSystem(ps);
        gPartAt = llGetTime();
    }
    else
    {
        llParticleSystem([]);
        if (band == 0)
        {
            glow = 0.10;
            lit = 0.22;
            lamp = TRUE;
        }
    }
    llSetPrimitiveParams([
        PRIM_GLOW, ALL_SIDES, glow,
        PRIM_POINT_LIGHT, lamp, <1.00, 0.32, 0.58>, lit, 1.4 + x * 1.6, 0.75
    ]);
    if (!PrimIsMesh())
    {
        string tex = "lovense_offline";
        if (band >= 1) tex = "lovense_active";
        else if (band == 0) tex = "lovense_online";
        if (llGetInventoryType(tex) == INVENTORY_TEXTURE)
            llSetTexture(tex, ALL_SIDES);
    }

    if (band >= 1 || (gOrbit && llGetNumberOfPrims() > 1))
        llSetTimerEvent(0.05);
    else
        llSetTimerEvent(0.0);
}

integer LinkSkip(integer i)
{
    string nm = llToLower(llGetLinkName(i));
    if (nm == "orb") return FALSE;
    if (llSubStringIndex(nm, "pink") >= 0) return FALSE;
    if (llSubStringIndex(nm, "cyan") >= 0) return FALSE;
    if (llSubStringIndex(nm, "core") >= 0) return FALSE;
    return TRUE;
}

CaptureRest()
{
    gRestSize = [];
    integer n = llGetNumberOfPrims();
    integer i;
    for (i = 2; i <= n; ++i)
    {
        list p = llGetLinkPrimitiveParams(i, [PRIM_SIZE]);
        gRestSize += llList2Vector(p, 0);
    }
}

RestLinks()
{
    integer n = llGetNumberOfPrims();
    integer i;
    for (i = 2; i <= n; ++i)
    {
        integer k = i - 2;
        if (k >= llGetListLength(gRestSize)) return;
        if (LinkSkip(i)) jump nxt;

        llSetLinkPrimitiveParamsFast(i, [
            PRIM_SIZE, llList2Vector(gRestSize, k)
        ]);
        @nxt;
    }
}

StartOrbit()
{
    if (!gOrbit)
    {
        llSetTimerEvent(0.0);
        RestLinks();
        return;
    }
    if (llGetNumberOfPrims() < 2)
    {
        llSetTimerEvent(0.0);
        if (!gOrbitWarned)
        {
            gOrbitWarned = TRUE;
            llOwnerSay("Look: orbit needs a linkset (Glass root + Pink/Cyan/Core children).");
        }
        return;
    }

    if (llGetListLength(gRestSize) != llGetNumberOfPrims() - 1)
        CaptureRest();

    llSetTimerEvent(0.05);
}

OrbitStep()
{
    integer n = llGetNumberOfPrims();
    if (n < 2) return;
    if (llGetListLength(gRestSize) != n - 1)
    {
        CaptureRest();
        return;
    }

    float t = llGetTime();
    integer i;
    integer k;
    integer orbIndex = 0;

    for (i = 2; i <= n; ++i)
    {
        if (LinkSkip(i)) jump nxt;
        k = i - 2;

        float userDist = 1.0;
        if (orbIndex < llGetListLength(LIST_DISTANCE_MODIFIERS))
            userDist = llList2Float(LIST_DISTANCE_MODIFIERS, orbIndex);

        float userSize = 1.0;
        if (orbIndex < llGetListLength(LIST_SIZE_MODIFIERS))
            userSize = llList2Float(LIST_SIZE_MODIFIERS, orbIndex);

        float userBeat = 1.0;
        if (orbIndex < llGetListLength(LIST_BEAT_MODIFIERS))
            userBeat = llList2Float(LIST_BEAT_MODIFIERS, orbIndex);

        // Each bead has its own pulse. Phase offset keeps them from
        // beating in lockstep even at the same tempo.
        float pulse = 1.0 + (HEARTBEAT_INTENSITY - 1.0) * llPow(llFabs(llSin(t * HEARTBEAT_SPEED * userBeat + (float)orbIndex)), 8.0);

        float currentRadius = BASE_RADIUS * userDist;

        float phi = t * SURFACE_SPEED * (1.2 + 0.3 * (float)orbIndex) + (float)orbIndex * 2.14;
        float theta = t * SURFACE_SPEED * 0.7 * (0.8 + 0.1 * (float)orbIndex) + (float)orbIndex * 1.57;

        float x = currentRadius * llSin(theta) * llCos(phi);
        float y = currentRadius * llSin(theta) * llSin(phi);
        float z = currentRadius * llCos(theta);

        vector surfacePos = <x, y, z>;

        rotation surfaceRot = llRotBetween(<0.0, 0.0, 1.0>, llVecNorm(surfacePos));

        vector origSize = llList2Vector(gRestSize, k);
        vector dynSize = origSize * pulse * userSize;

        llSetLinkPrimitiveParamsFast(i, [
            PRIM_POS_LOCAL, surfacePos,
            PRIM_ROT_LOCAL, surfaceRot,
            PRIM_SIZE, dynSize
        ]);

        orbIndex++;

        @nxt;
    }
}

ApplyLook(string str)
{
    if (llGetSubString(str, 0, 6) != "LOOK|") return;
    list p = llParseString2List(str, ["|"], []);
    string k = llList2String(p, 1);
    if (k == "fx")
    {
        gVib = (integer)llList2String(p, 2);
        gVMax = (integer)llList2String(p, 3);
        gConnected = (integer)llList2String(p, 4);
        gPaired = (integer)llList2String(p, 5);
        if (gVMax < 1) gVMax = 20;
        if (llGetListLength(p) > 6)
        {
            key a = (key)llList2String(p, 6);
            if (a != gAim)
            {
                gAim = a;
                gFxBand = -9;
            }
        }
        Fx();
        return;
    }
    if (k == "orbit")
    {
        gOrbit = (integer)llList2String(p, 2);
        llLinksetDataWrite("lv.orbit", (string)gOrbit);
        StartOrbit();
        return;
    }
    if (k == "init")
    {
        EnsureOrb();
        Fx();
        StartOrbit();
    }
}

default
{
    state_entry()
    {
        if (llGetLinkNumber() > 1)
        {
            llOwnerSay("Look script belongs in Glass (root). Removing this copy.");
            llRemoveInventory(llGetScriptName());
            return;
        }
        gVib = 0;
        gVMax = 20;
        gConnected = FALSE;
        gPaired = FALSE;
        gFxBand = -9;
        gOrbit = TRUE;
        gOrbitWarned = FALSE;
        gPartAt = -10.0;
        gAim = NULL_KEY;
        gFxAim = NULL_KEY;
        gRestSize = [];
        string o = llLinksetDataRead("lv.orbit");
        if (o != "") gOrbit = (integer)o;
        EnsureOrb();
        Fx();
        StartOrbit();
    }

    on_rez(integer p)
    {
        EnsureOrb();
        gFxBand = -9;
        Fx();
        gRestSize = [];
        StartOrbit();
    }

    attach(key id)
    {
        if (id != NULL_KEY)
        {
            EnsureOrb();
            gFxBand = -9;
            Fx();
            gRestSize = [];
            StartOrbit();
        }
    }

    changed(integer change)
    {
        if (change & CHANGED_LINK)
        {
            gRestSize = [];
            StartOrbit();
        }
        if (change & CHANGED_INVENTORY)
        {
            gFxBand = -9;
            Fx();
        }
    }

    timer()
    {
        if (gOrbit) OrbitStep();
        if (gFxBand >= 1 && (llGetTime() - gPartAt) >= 2.5)
        {
            gPartAt = llGetTime();
            gFxBand = -9;
            Fx();
        }
    }

    link_message(integer sender, integer num, string str, key id)
    {
        if (num != 0xC07E) return;
        if (llGetSubString(str, 0, 2) == "LV|")
        {
            list p = llParseString2List(str, ["|"], []);
            string k = llList2String(p, 1);
            if (k == "stop")
            {
                gVib = 0;
                gAim = NULL_KEY;
                gFxBand = -9;
                Fx();
                return;
            }
            if (k == "vibe" || k == "queue")
            {
                gVib = (integer)llList2String(p, 2);
                gVMax = (integer)llList2String(p, 3);
                if (gVMax < 1) gVMax = 20;
                if (gVib > 0) gConnected = TRUE;
                gPaired = TRUE;
                Fx();
            }
            return;
        }
        ApplyLook(str);
    }
}
