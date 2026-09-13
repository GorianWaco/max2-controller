// Child prim: płynnie przybliża się i oddala od root,
// wolno się kręci i lekko oddycha rozmiarem.
// Wrzuć ten skrypt TYLKO do child prima (nie do root).
//
// Pozycja: wzdłuż linii root → child. Może nachodzić i przenikać root.
// Obrót: wokół osi childa (domyślnie jego lokalne Z).
// Skala: ten sam sinus co pozycja — bliżej = mniejszy, dalej = większy.

float PERIOD     = 12.0;            // sekundy na cykl przybliż/oddal + oddech
float AMP        = 0.20;            // ±20% odległości od root (gdy child jest odsunięty)
float MIN_TRAVEL = 0.15;            // minimalny ruch w metrach — działa też wewnątrz root
float SCALE_AMP  = 0.08;            // ±8% rozmiaru (lekko)
float ROT_PERIOD = 22.0;            // sekundy na pełny obrót
vector ROT_AXIS  = <0.0, 0.0, 1.0>; // lokalna oś obrotu childa
float STEP       = 0.05;            // timer; 0.05 ≈ 20 klatek/s

vector   gRestPos;
rotation gRestRot;
vector   gRestScale;
vector   gDir;
float    gTravel;

float ClampAxis(float v)
{
    if (v < 0.01) return 0.01;
    if (v > 64.0) return 64.0;
    return v;
}

vector ClampSize(vector size)
{
    size.x = ClampAxis(size.x);
    size.y = ClampAxis(size.y);
    size.z = ClampAxis(size.z);
    return size;
}

default
{
    state_entry()
    {
        integer link = llGetLinkNumber();
        if (link <= 1)
        {
            llOwnerSay("Ten skrypt ma być w CHILD primie, nie w root.");
            return;
        }

        gRestPos = llGetLocalPos();
        gRestRot = llGetLocalRot();
        gRestScale = llGetScale();

        float mag = llVecMag(gRestPos);
        if (mag > 0.001) gDir = gRestPos / mag;
        else gDir = llVecNorm(ROT_AXIS);

        gTravel = mag * AMP;
        if (gTravel < MIN_TRAVEL) gTravel = MIN_TRAVEL;

        llSetTimerEvent(STEP);
    }

    on_rez(integer start_param)
    {
        llResetScript();
    }

    changed(integer change)
    {
        if (change & (CHANGED_LINK | CHANGED_REGION_START | CHANGED_TELEPORT))
            llResetScript();
    }

    timer()
    {
        float t = llGetTime();
        float s = llSin(TWO_PI * t / PERIOD);
        float yaw = TWO_PI * t / ROT_PERIOD;

        vector pos = gRestPos + gDir * gTravel * s;
        vector scale = ClampSize(gRestScale * (1.0 + SCALE_AMP * s));
        rotation rot = gRestRot * llAxisAngle2Rot(llVecNorm(ROT_AXIS), yaw);

        llSetLinkPrimitiveParamsFast(LINK_THIS, [
            PRIM_POS_LOCAL, pos,
            PRIM_ROT_LOCAL, rot,
            PRIM_SIZE, scale
        ]);
    }
}
