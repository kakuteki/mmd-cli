"""A soft self shadow for MMD through MikuMikuEffect (MME): the effect file that draws a model's body with MMD's own
shading but reads the self shadow map at many points weighted by a Gaussian, and the files round it.

    python tools/mme_shadow.py write OUT.fx [--blur 5] [--min-blur 0.05] [--taps 64] [--search-taps 64] [--key-share 0.35 | --toon]
                                     [--debug [shadow|lit]] [--sharp]
    python tools/mme_shadow.py prepare MODEL.pmx OUTDIR [--variant NAME] [the options of write]
    python tools/mme_shadow.py check MMD.exe
    python tools/mme_shadow.py verify MMD.exe MODEL.pmx soft|mmd

What it changes, and what not.  MMD draws a model in passes; MME lets an effect file replace any of them, and draws the
others with MMD's own shaders (REFERENCE.txt of MME 0.37, 1.2 and the Tips).  This effect has techniques for one pass
only: "object_ss", the body while the self shadow is shown.  The shadow map is MMD's own ("zplot" stays MMD's), the
outline ("edge"), the ground shadow ("shadow") and the body without the self shadow ("object") stay MMD's.  So with the
self shadow display off (menu 279) nothing changes, and a model without the effect is drawn as before.

The body's shading follows MMD's standard shading as MME exposes it (ambient + emissive, the toon colour, texture,
sphere map, specular, MMD's own shadow test: 1 - saturate(max(z - map, 0) * 1500 - 0.3) in mode 1, the slope 8000 x v in
mode 2).  Only the shadow test differs: it is done at --taps points of the shadow map round the pixel's own point,
laid as a Gaussian lies (the same weight each, their radii its quantiles), and their mean is the shadow.  The
Gaussian's spread on the shadow map:

* with contact hardening (the default) it is the spread of a light --blur degrees wide (a standard deviation) at the
  distance from the shadowed point back to what casts the shadow (a search of --search-taps points, 64 by default, from
  3 % of its radius out to all of it on a logarithm of the radius, finds the casters' gaps and takes their mean: plain
  by default, HARMONIC; the harmonic mean, where the nearest caster rules, speckled and lined the penumbra, review of
  softshadow-mme2; with none found the least blur stays; a depth gap over the depth's rate along the light is a
  distance along the light, and a distance across the light times |x| / 2 of the light's matrix is a share of the
  map).  An arm on the dress casts a shadow whose edge blurs with the gap, as tools/mv_world.py's floor shadow does
  with the same --blur;
* never under --min-blur (a standard deviation in MMD units): the stair steps of MMD's map (some 4.5 mm on the dress at
  the default shadow distance) are blurred away even where the gap is 0.

Every point of the map round the pixel (the search and the Gaussian) is compared with the depth the receiver's own plane
has there, not with the pixel's own depth.  MMD's light depth does not run along the light (review of softshadow-mme;
read from the matrix MME gives, softshadow-mme2: the matrix divides by a w that changes across the light (its fourth
column 0.005 or more a unit), so the map is a warped picture whose depth slants across the light), so on the pixel's
own plane a point beside it on the map lies nearer or further in depth: compared with the pixel's depth, the search took
the receiver itself for what casts the shadow (gaps of 0.65 to 1.7 units where they were 2.6 to 9.6, and an edge of
about the same spread at every distance) and the points of the Gaussian shadowed a lit face (acne: a wall nothing
shadows at 0.83).  The plane is the receiver's (interpolated) normal under the light's own matrix (plane_slope; the normal
held at least FACING_MIN towards the light, a face along the light having no depth of its own), and a depth gap is
turned into a distance along the light with that matrix too (along_light).  And what the search finds above the
receiver's plane counts as a caster only within the light's spread from the pixel (in_cone: KERNEL_SIGMAS standard
deviations of the light at its distance along the light): a thing beside the pixel and not above it (the next plate of
the review's fan) casts no shadow on it, and a point of the receiver's own surface that the plane does not quite match
(a small gap beside the pixel) is not taken for a caster.

How dark the shade is: MMD shades with the toon's colour (this model's keep 72 to 89 % of the light), while
tools/mv_world.py's floor takes KEY_SHARE (0.6) of its light from the key light and keeps the rest in a shadow.  The
shade keeps 1 - --key-share of the light: the toon's colour keeps its hue and its luma (BT.709, as tools/shadow_check.py
reads the floor) is set to 1 - key_share, on the shadowed side and in the shadow alike, as on the floor.  By default
--key-share 0.35: the shade keeps 0.65 (option D, Kaga-san's choice of 2026-10-17), lighter than the floor's shadow
(0.40: stage.shadow_key 0.6); --key-share 0.6 is option A, the shade as dark as the floor's.  A material whose toon is
white (here the face and the eyes: MMD draws no shade on them) is left so.  --toon keeps MMD's toon colours as they are.

--sharp writes the same file with one point and no blur and MMD's toon colours: MMD's own test (to check that the
shading is MMD's).  --debug draws the shadow alone (white lit, black shadowed, opaque) for tools/shadow_measure.py;
--debug lit draws the body lit everywhere (no shade, no shadow), to read what a shade keeps of the light; --debug toon
draws the toon's share of the light where a shade shows (0 on a white toon), for tools/selfshadow_check.py against.
The file is ASCII.

prepare copies the folder of MODEL (its textures) into OUTDIR, and again each file that changed since the last copy, and
writes the effect there under the model's name (MME applies <model name>.fx found beside the model when MMD loads it;
MMEffect.txt).  The original folder is not written.  check tells whether MME is installed beside an MMD (d3d9.dll,
MMHack.dll, MMEffect.dll, by their SHA-256).  verify tells whether an MMD will draw a model with this effect (soft) or
with MMD's own self shadow (mmd): tools/mv_chunks.py's driver runs it before rendering, so a plan that says soft cannot
quietly render MMD's shadow or an effect for measuring (--debug, --sharp), nor one that says mmd the effect (beside any
MMEffect.dll, of this build or another).
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import sys

# MME 0.37 x64 as taken from its distribution (BowlRoll file 35013, 2026-10-17; softshadow-mme NOTES)
MME_FILES = {"d3d9.dll": "3c1c663c4b2fda0c92a97fc2d3d01fd1fb4110ae552e68f284657b72c74cfac8",
             "MMHack.dll": "e450b25e5cd2bcf125ca4b8eb9e57f858ec3ca379633c7d25f9dd40e864b390d",
             "MMEffect.dll": "74b3f5882a3bad28131cbc57994e2f960938e6ca850fc7139018ce4822bd87dc"}
KERNEL_SIGMAS = 2.5               # the points lie within this many standard deviations of the Gaussian
# the standard deviation of a Gaussian of 1 cut at KERNEL_SIGMAS (along an axis): the points are widened by its inverse,
# so that their spread is the light's (cut, an edge came out 0.925 of it)
CUT_STD = math.sqrt((1.0 - (1.0 + 0.5 * KERNEL_SIGMAS ** 2) * math.exp(-0.5 * KERNEL_SIGMAS ** 2))
                    / (1.0 - math.exp(-0.5 * KERNEL_SIGMAS ** 2)))
GOLDEN = math.pi * (3.0 - math.sqrt(5.0))
# key_share 0.35: the shade keeps 0.65 of the light, option D (Kaga-san's choice of 2026-10-17 among A: the shade 0.40,
# B: MMD's toon, C: the shade and the floor 0.65, D: the shade 0.65 and the floor 0.40); the floor's shadow keeps
# 1 - stage.shadow_key = 0.40 (tools/mv_world.py KEY_SHARE 0.6)
DEFAULTS = {"blur": 5.0, "min_blur": 0.05, "taps": 64, "search_taps": 64, "contact": True, "key_share": 0.35}
# the casters' gaps found by the search are averaged plainly (0) or harmonically (1: the nearest caster rules).  Review
# of softshadow-mme2, against the reference of a 5 degree light (MMD's own hard shadow under 64 directions of the light,
# averaged; tools/selfshadow_check.py against) at 4 frames of the dancer: with the harmonic mean over 16 points one
# search point that found a near thing (a fold of the dress) shrank the blur of its pixel alone, and the penumbra came
# out speckled and lined (8.4 % of its pixels brighter or darker than both neighbours across it; MMD's own 2.1 %) with
# its outer edge cut (4.5 % of its tail all lit).  The plain mean over 64 search points and 64 Gaussian points: 2.4 %
# and 0.4 %, the mean error from the reference the same (0.026 against 0.027)
HARMONIC = 0
FACING_MIN = 0.25         # the receiver's normal is held at least this far towards the light (75.5 degrees from it) when
                          # the plane round the pixel is worked out: a face along the light has no depth of its own
DEBUGS = {False: 0, None: 0, True: 1, "shadow": 1, "lit": 2, "toon": 3}
SEARCH_INNER = 0.03       # the innermost point of the search, a share of its radius (0.054 units: a caster's cone near
                          # the pixel is small, 0.38 units at 1.5 for 5 degrees)
SEARCH = 1.8              # MMD units round the point the casters are looked for (2.5 standard deviations of a 5 degree
                          # light at 8 units: the hips above the knees)


def taps(n):
    """the points of the Gaussian: (x, y, 1 / n) in standard deviations, n points of the same weight whose radii are the
    quantiles of the Gaussian's radius (its integral 1 - exp(-r^2 / 2)) cut at KERNEL_SIGMAS and widened by 1 / CUT_STD
    (a standard deviation of 1 along any axis), round the golden angle.  An
    edge passing across them steps by 1 / n (with even radii and Gaussian weights, before softshadow-mme2, the inner
    points weighed 3 to 5 times the mean and a wide shadow showed its copies)"""
    top = 1.0 - math.exp(-0.5 * KERNEL_SIGMAS ** 2)
    out = []
    for i in range(n):
        r = math.sqrt(-2.0 * math.log(1.0 - (i + 0.5) / n * top)) / CUT_STD
        a = i * GOLDEN
        out.append((r * math.cos(a), r * math.sin(a), 1.0 / n))
    return out


def search_points(n):
    """the points of the search for casters: (x, y, 1) from SEARCH_INNER of its radius out to all of it, evenly on a
    logarithm of the radius (a caster near the pixel counts only within a small cone, in_cone), round the golden angle"""
    if n == 1:
        return [(0.0, 0.0, 1.0)]
    out = []
    for i in range(n):
        r = SEARCH_INNER ** (1.0 - i / float(n - 1))
        a = i * GOLDEN
        out.append((r * math.cos(a), r * math.sin(a), 1.0))
    return out


def _array(name, rows, fmt):
    body = ",\n".join("    float3(%s)" % ", ".join(fmt % v for v in row) for row in rows)
    return "static const float3 %s[%d] = {\n%s\n};\n" % (name, len(rows), body)


def effect(blur=DEFAULTS["blur"], min_blur=DEFAULTS["min_blur"], n_taps=DEFAULTS["taps"],
           search_taps=DEFAULTS["search_taps"], contact=DEFAULTS["contact"], debug=False, sharp=False,
           key_share=DEFAULTS["key_share"]):
    """the text of the effect file (see the module docstring).  key_share None: MMD's toon colours"""
    if debug not in DEBUGS:
        raise ValueError("--debug is shadow or lit, not %r" % (debug,))
    if key_share is not None and (isinstance(key_share, bool) or not 0 <= key_share < 1):
        raise ValueError("--key-share is the key light's share of the light, 0 to under 1, not %r" % (key_share,))
    if not 0 <= blur <= 30:
        raise ValueError("--blur is the light's spread in degrees, 0 to 30, not %r" % (blur,))
    if not 0 <= min_blur <= 2:
        raise ValueError("--min-blur is a standard deviation in MMD units, 0 to 2, not %r" % (min_blur,))
    if sharp:
        n_taps, search_taps, contact, min_blur, blur, key_share = 1, 1, False, 0.0, 0.0, None
    if not 1 <= n_taps <= 64 or not 1 <= search_taps <= 64:
        raise ValueError("--taps and --search-taps are 1 to 64")
    kernel = [(0.0, 0.0, 1.0)] if n_taps == 1 else taps(n_taps)
    search = search_points(search_taps)
    debug = {0: False, 1: "shadow", 2: "lit", 3: "toon"}[DEBUGS[debug]]
    settings = {"blur": blur, "min_blur": min_blur, "taps": n_taps, "search_taps": search_taps, "contact": bool(contact),
                "debug": debug, "sharp": bool(sharp), "key_share": key_share}
    head = ("// soft_self_shadow.fx: MMD's body pass with the self shadow (object_ss) read at many points of the shadow map\n"
            "// weighted by a Gaussian.  Written by tools/mme_shadow.py (mmd-cli) from MME 0.37's REFERENCE.txt; the other\n"
            "// passes are MMD's own.  Settings: %s\n" % json.dumps(settings, sort_keys=True))
    defines = ("#define SS_BLUR_RAD %.9f\n#define SS_MIN_WORLD %.6f\n#define SS_TAPS %d\n#define SS_SEARCH %d\n"
               "#define SS_CONTACT %d\n#define SS_DEBUG %d\n#define SS_SEARCH_WORLD %.6f\n#define SS_ALIGN %d\n"
               "#define SS_KEEP %.6f\n#define SS_FACING_MIN %.6f\n#define SS_CONE %.6f\n#define SS_HARMONIC %d\n"
               % (math.radians(blur), min_blur, len(kernel), len(search), 1 if contact else 0, DEBUGS[debug], SEARCH,
                  0 if key_share is None else 1, 1.0 if key_share is None else 1.0 - key_share, FACING_MIN, KERNEL_SIGMAS,
                  HARMONIC))
    return (head + defines + _array("KERNEL", kernel, "%.7f") + _array("SEARCH", search, "%.7f") + BODY)



BODY = r"""
float4x4 WorldViewProjMatrix      : WORLDVIEWPROJECTION;
float4x4 WorldMatrix              : WORLD;
float4x4 ViewMatrix               : VIEW;
float4x4 LightWorldViewProjMatrix : WORLDVIEWPROJECTION < string Object = "Light"; >;
float3   LightDirection : DIRECTION < string Object = "Light"; >;
float3   CameraPosition : POSITION  < string Object = "Camera"; >;

float4 MaterialDiffuse  : DIFFUSE  < string Object = "Geometry"; >;
float3 MaterialAmbient  : AMBIENT  < string Object = "Geometry"; >;
float3 MaterialEmissive : EMISSIVE < string Object = "Geometry"; >;
float3 MaterialSpecular : SPECULAR < string Object = "Geometry"; >;
float  SpecularPower    : SPECULARPOWER < string Object = "Geometry"; >;
float3 MaterialToon     : TOONCOLOR;
float3 LightDiffuse     : DIFFUSE  < string Object = "Light"; >;
float3 LightAmbient     : AMBIENT  < string Object = "Light"; >;
float3 LightSpecular    : SPECULAR < string Object = "Light"; >;
static float4 DiffuseColor  = MaterialDiffuse * float4(LightDiffuse, 1.0f);
static float3 AmbientColor  = MaterialAmbient * LightAmbient + MaterialEmissive;
static float3 SpecularColor = MaterialSpecular * LightSpecular;

float4 TextureAddValue : ADDINGTEXTURE;
float4 TextureMulValue : MULTIPLYINGTEXTURE;
float4 SphereAddValue  : ADDINGSPHERETEXTURE;
float4 SphereMulValue  : MULTIPLYINGSPHERETEXTURE;

bool parthf;
bool transp;
bool spadd;
bool use_subtexture;

// MMD keeps its own samplers in s0 to s2 (the self shadow map is in s0): the effect's own come after them
sampler MMDShadowMap : register(s0);
sampler MMDSampler1 : register(s1);
sampler MMDSampler2 : register(s2);

texture ObjectTexture : MATERIALTEXTURE;
sampler ObjTexSampler = sampler_state {
    texture = <ObjectTexture>;
    MINFILTER = LINEAR;
    MAGFILTER = LINEAR;
#ifdef MME_MIPMAP
    MIPFILTER = LINEAR;
#endif
    ADDRESSU = WRAP;
    ADDRESSV = WRAP;
};

texture ObjectSphereMap : MATERIALSPHEREMAP;
sampler ObjSphereSampler = sampler_state {
    texture = <ObjectSphereMap>;
    MINFILTER = LINEAR;
    MAGFILTER = LINEAR;
#ifdef MME_MIPMAP
    MIPFILTER = LINEAR;
#endif
    ADDRESSU = WRAP;
    ADDRESSV = WRAP;
};

#ifndef SS_MORPHS
#define SS_MORPHS 0
#endif
// the texture and the sphere map are read through MMD's own samplers (s1, s2: MMD binds them there, with its own
// filtering): through samplers of the effect's own the picture differed at the textures' fine lines (4 to 30 levels at
// 3,200 px of a frame), through MMD's it differs by 1 level at most but at 84 px (NOTES)
// the casters' gaps: SS_HARMONIC 1 averages them harmonically (the nearest caster rules), 0 plainly.  The plain mean is
// the default (tools/mme_shadow.py HARMONIC, review of softshadow-mme2: one near hit of the harmonic mean shrank the blur
// of its pixel alone, a speckled and lined penumbra); an effect written without the define keeps the harmonic mean
#ifndef SS_HARMONIC
#define SS_HARMONIC 1
#endif
#ifndef SS_MMD_SAMPLER
#define SS_MMD_SAMPLER 2
#endif
#define SKII1 1500.0
#define SKII2 8000.0
#define TOON_SLOPE 3.0

struct SS_OUT {
    float4 Pos      : POSITION;
    float4 ZCalcTex : TEXCOORD0;
    float2 Tex      : TEXCOORD1;
    float3 Normal   : TEXCOORD2;
    float3 Eye      : TEXCOORD3;
    float2 SpTex    : TEXCOORD4;
    float3 ObjNormal : TEXCOORD5;
    float4 Color    : COLOR0;
};

SS_OUT SS_VS(float4 Pos : POSITION, float3 Normal : NORMAL, float2 Tex : TEXCOORD0, float2 Tex2 : TEXCOORD1,
             uniform bool useTexture, uniform bool useSphereMap, uniform bool useToon)
{
    SS_OUT Out = (SS_OUT)0;
    Out.Pos = mul(Pos, WorldViewProjMatrix);
    Out.Eye = CameraPosition - mul(Pos, WorldMatrix).xyz;
    Out.Normal = normalize(mul(Normal, (float3x3)WorldMatrix));
    Out.ObjNormal = Normal;
    Out.ZCalcTex = mul(Pos, LightWorldViewProjMatrix);
    Out.Color.rgb = AmbientColor;
    if (!useToon) {
        Out.Color.rgb += max(0, dot(Out.Normal, -LightDirection)) * DiffuseColor.rgb;
    }
    Out.Color.a = DiffuseColor.a;
    Out.Color = saturate(Out.Color);
    Out.Tex = Tex;
    if (useSphereMap) {
        if (use_subtexture) {
            Out.SpTex = Tex2;
        } else {
            float2 NormalWV = mul(Out.Normal, (float3x3)ViewMatrix).xy;
            Out.SpTex.x = NormalWV.x * 0.5f + 0.5f;
            Out.SpTex.y = NormalWV.y * -0.5f + 0.5f;
        }
    }
    return Out;
}

// MMD's own shadow test at one point of the map: 1 lit, 0 in the shadow (with its narrow ramp)
float ShadowTest(float z, float2 uv, float slope)
{
    if (any(saturate(uv) != uv)) {
        return 1.0f;
    }
    return 1.0f - saturate(max(z - tex2Dlod(MMDShadowMap, float4(uv, 0, 0)).r, 0.0f) * slope - 0.3f);
}

// the light's matrix from the model to the map by columns: x and y place a point on the map, z is its depth.  MMD's depth
// does not run along the light (review of softshadow-mme: its gradient some 53 degrees off it), so on the receiver's own
// plane a point beside the pixel on the map has a depth of its own: every comparison round the pixel is made with that
static float3 LightX = float3(LightWorldViewProjMatrix._11, LightWorldViewProjMatrix._21, LightWorldViewProjMatrix._31);
static float3 LightY = float3(LightWorldViewProjMatrix._12, LightWorldViewProjMatrix._22, LightWorldViewProjMatrix._32);
static float3 LightZ = float3(LightWorldViewProjMatrix._13, LightWorldViewProjMatrix._23, LightWorldViewProjMatrix._33);
// MMD's light matrix divides by w (its fourth column is not 0: softshadow-mme2): round a point the map's x, y and depth
// change by these columns less the perspective's share there, (c - ndc c3) / w; w stays the same along the light
static float3 LightW = float3(LightWorldViewProjMatrix._14, LightWorldViewProjMatrix._24, LightWorldViewProjMatrix._34);
// where the light shines to, in the model's own space (the matrix above takes the model's points)
static float3 LightObj = normalize(mul((float3x3)WorldMatrix, LightDirection));

// the depth of the receiver's plane per u and per v of the map (tools/mme_shadow.py plane_slope): the plane's points
// beside the pixel solve x, y on the map and lie on the plane; the normal is held at least SS_FACING_MIN towards the light
// (a face along the light has no depth of its own, one turned from it lies in its own shade)
float2 PlaneSlope(float3 n, float3 ndc)
{
    float3 toward = -LightObj;
    float facing = dot(n, toward);
    if (facing < SS_FACING_MIN) {
        float3 side = n - facing * toward;
        float s = length(side);
        side = s > 1e-5f ? side / s : float3(0.0f, 0.0f, 0.0f);
        n = side * sqrt(1.0f - SS_FACING_MIN * SS_FACING_MIN) + toward * SS_FACING_MIN;
    }
    // the columns round the pixel (their common 1 / w drops out of the slope)
    float3 x = LightX - ndc.x * LightW;
    float3 y = LightY - ndc.y * LightW;
    float3 z = LightZ - ndc.z * LightW;
    float3 a = cross(y, n);
    float3 b = cross(n, x);
    float det = dot(x, a);
    return float2(2.0f * dot(z, a), -2.0f * dot(z, b)) / det;
}

float SoftShadow(float3 zc, float2 uv, float2 plane, float w)
{
    float slope = parthf ? SKII2 * uv.y : SKII1;
    // round the pixel a world length across the light times |x| / 2 is a share of the map (the light's perspective there)
    float perUnit = 0.25f * (length(LightX - zc.x * LightW) + length(LightY - zc.y * LightW)) / max(w, 1e-6f);
    float spread = SS_MIN_WORLD * perUnit;
    // a depth gap over the depth's rate along the light there (tools/mme_shadow.py along_light) is the distance along it
    float rate = max(dot(LightZ - zc.z * LightW, LightObj) / max(w, 1e-6f), 1e-9f);
#if SS_CONTACT
    // the casters' mean depth round the point: the gap to them is a distance along the light
    float gap = 0.0f;
    float found = 0.0f;
    for (int j = 0; j < SS_SEARCH; j++) {
        float2 off = SEARCH[j].xy * (SS_SEARCH_WORLD * perUnit);
        float2 p = uv + off;
        if (all(saturate(p) == p)) {
            float d = tex2Dlod(MMDShadowMap, float4(p, 0, 0)).r;
            float zr = zc.z + dot(plane, off);
            if ((zr - d) * slope > 0.3f) {
                // above the receiver's plane, but a caster only within the light's spread from the pixel (in_cone): a
                // thing beside the pixel and not above it casts no shadow on it
                float along = (zr - d) / rate;
                if (length(off) / perUnit <= SS_CONE * SS_BLUR_RAD * along + SS_MIN_WORLD) {
#if SS_HARMONIC
                    gap += 1.0f / max(zr - d, 1e-7f);
#else
                    gap += zr - d;
#endif
                    found += 1.0f;
                }
            }
        }
    }
    // with no caster in the cone the least blur stays (not MMD's hard test: a shadow's edge near what casts it was hard
    // or soft from one pixel to the next, review of softshadow-mme2)
    if (found > 0.5f) {
#if SS_HARMONIC
        // the casters' harmonic mean: the nearest caster rules (an arm over the dress)
        gap = found / gap;
#else
        gap /= found;
#endif
        float across = SS_BLUR_RAD * gap / rate * perUnit;
        spread = max(spread, across);
    }
#endif
    float lit = 0.0f;
    for (int i = 0; i < SS_TAPS; i++) {
        float2 off = KERNEL[i].xy * spread;
        lit += KERNEL[i].z * ShadowTest(zc.z + dot(plane, off), uv + off, slope);
    }
    return lit;
}

float4 SS_PS(SS_OUT IN, uniform bool useTexture, uniform bool useSphereMap, uniform bool useToon) : COLOR0
{
    float3 HalfVector = normalize(normalize(IN.Eye) + -LightDirection);
    float3 Specular = pow(max(0, dot(HalfVector, normalize(IN.Normal))), SpecularPower) * SpecularColor;
    float4 Color = IN.Color;
    // MMD's shade is the lit colour (saturated) times the toon's colour: measured on its own render of the model with
    // white textures (the lit share goes from the toon colour at N.L 0 to white at N.L 1/3, the map's shadow keeps the
    // toon colour); full.fx's unsaturated ambient would leave the shade white where ambient + emissive passes 1
    float4 ShadowColor = float4(saturate(AmbientColor), Color.a);
    if (useTexture) {
#if SS_MMD_SAMPLER
        float4 TexColor = tex2D(MMDSampler1, IN.Tex);
#else
        float4 TexColor = tex2D(ObjTexSampler, IN.Tex);
#endif
#if SS_MORPHS
        TexColor = TexColor * TextureMulValue + TextureAddValue;
#endif
        Color *= TexColor;
        ShadowColor *= TexColor;
    }
    if (useSphereMap) {
#if SS_MMD_SAMPLER >= 2
        float4 TexColor = tex2D(MMDSampler2, IN.SpTex);
#else
        float4 TexColor = tex2D(ObjSphereSampler, IN.SpTex);
#endif
#if SS_MORPHS
        TexColor = TexColor * SphereMulValue + SphereAddValue;
#endif
        if (spadd) {
            Color.rgb += TexColor.rgb;
            ShadowColor.rgb += TexColor.rgb;
        } else {
            Color.rgb *= TexColor.rgb;
            ShadowColor.rgb *= TexColor.rgb;
        }
    }
    Color.rgb += Specular;
#if SS_DEBUG == 2
    // lit everywhere: no shade and no shadow (what a shade keeps of the light is its colour over this)
    if (transp) {
        Color.a = 0.5f;
    }
    return Color;
#endif
#if SS_DEBUG == 3
    // the toon's share of the light where a shade shows, 0 where none can (no toon, or a white one: MMD draws no shade
    // there): where it is 1 the shadow is what shows (tools/selfshadow_check.py against --toon)
    float tshare = (useToon && dot(MaterialToon, float3(0.2126f, 0.7152f, 0.0722f)) < 0.999f)
                   ? saturate(dot(IN.Normal, -LightDirection) * TOON_SLOPE) : 0.0f;
    return float4(tshare, tshare, tshare, 1.0f);
#endif
    float3 zc = IN.ZCalcTex.xyz / IN.ZCalcTex.w;
    float2 uv = float2((1.0f + zc.x) * 0.5f, (1.0f - zc.y) * 0.5f);
    float2 plane = PlaneSlope(normalize(IN.ObjNormal), zc);
    if (any(saturate(uv) != uv)) {
        // outside the shadow map MMD draws the body lit, without the toon's shade
#if SS_DEBUG == 1
        return float4(1.0f, 1.0f, 1.0f, 1.0f);
#endif
        return Color;
    }
    float comp = SoftShadow(zc, uv, plane, IN.ZCalcTex.w);
#if SS_DEBUG == 1
    return float4(comp, comp, comp, 1.0f);
#endif
    if (useToon) {
        comp = min(saturate(dot(IN.Normal, -LightDirection) * TOON_SLOPE), comp);
        float3 toon = MaterialToon;
#if SS_ALIGN
        // the shade keeps SS_KEEP of the light, as the floor of tools/mv_world.py does in a shadow: the toon's colour
        // keeps its hue, its luma (BT.709) is set to SS_KEEP; a white toon (no shade drawn: the face) stays white
        float luma = dot(toon, float3(0.2126f, 0.7152f, 0.0722f));
        if (luma < 0.999f) {
            toon = min(toon * (SS_KEEP / max(luma, 1e-4f)), 1.0f);
        }
#endif
        ShadowColor.rgb *= toon;
    }
    float4 ans = lerp(ShadowColor, Color, comp);
    if (transp) {
        ans.a = 0.5f;
    }
    return ans;
}

#define SS_TECH(name, tex, sph, toon) \
    technique name < string MMDPass = "object_ss"; bool UseTexture = tex; bool UseSphereMap = sph; bool UseToon = toon; > { \
        pass DrawObject { \
            VertexShader = compile vs_3_0 SS_VS(tex, sph, toon); \
            PixelShader  = compile ps_3_0 SS_PS(tex, sph, toon); \
        } \
    }

SS_TECH(SS_000, false, false, false)
SS_TECH(SS_100, true, false, false)
SS_TECH(SS_010, false, true, false)
SS_TECH(SS_110, true, true, false)
SS_TECH(SS_001, false, false, true)
SS_TECH(SS_101, true, false, true)
SS_TECH(SS_011, false, true, true)
SS_TECH(SS_111, true, true, true)
"""


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _columns(matrix, point=None):
    """the light's matrix (D3D rows: a point P goes to (P, 1) M, the map's place and depth (x, y, z) / w) by how x, y and
    the depth change per unit of the model round `point`: its first three columns less the perspective's share there,
    (c - ndc c3) / w (MMD's light matrix divides by w, its fourth column c3 is not 0: softshadow-mme2; w stays the same
    along the light).  Without a point, the columns as they are; and w"""
    cols = [tuple(float(matrix[i][j]) for i in range(3)) for j in range(4)]
    if point is None:
        return cols[:3], 1.0
    clip = [sum(float(point[i]) * float(matrix[i][j]) for i in range(3)) + float(matrix[3][j]) for j in range(4)]
    w = clip[3]
    return [tuple((c - clip[k] / w * d) / w for c, d in zip(cols[k], cols[3])) for k in range(3)], w


def plane_slope(matrix, normal, light, facing_min=FACING_MIN, point=None):
    """(per u, per v): how the depth of the receiver's own plane changes over the map round the pixel, as the effect
    works it out (PlaneSlope): `matrix` the light's (the model to the map's clip space; the map at uv = ((1 + x) / 2,
    (1 - y) / 2)), `normal` the receiver's, `light` where the light shines to.  The plane's point at an offset on the map
    solves x and y there and lies on the plane; its depth is the slope times the offset (to first order round `point`,
    the receiver, with the light's perspective).  The normal is held at least facing_min towards the light first (a
    face along the light has no depth of its own on the map)"""
    (c0, c1, c2), _ = _columns(matrix, point)
    toward = tuple(-x for x in _unit(light))
    n = _unit(normal)
    facing = _dot(n, toward)
    if facing < facing_min:
        side = tuple(a - facing * b for a, b in zip(n, toward))
        s = math.sqrt(_dot(side, side))
        side = tuple(x / s for x in side) if s > 1e-5 else (0.0, 0.0, 0.0)
        n = tuple(a * math.sqrt(1.0 - facing_min * facing_min) + b * facing_min for a, b in zip(side, toward))
    a = _cross(c1, n)
    b = _cross(n, c0)
    det = _dot(c0, a)
    return 2.0 * _dot(c2, a) / det, -2.0 * _dot(c2, b) / det


def along_light(matrix, light, gap, point=None):
    """the distance along the light that a depth gap of the map is: the gap over the depth's rate along the light at the
    receiver `point` (from the matrix, with its perspective)"""
    (_, _, c2), _ = _columns(matrix, point)
    return gap / _dot(c2, _unit(light))


def in_cone(side, along, blur, least):
    """does a thing `side` units across the light from the pixel and `along` units up the light from its plane cast a
    shadow on it, under a light `blur` degrees wide (a standard deviation; the effect's search): within KERNEL_SIGMAS of
    the light's spread at that distance, or the least blur `least`"""
    return side <= KERNEL_SIGMAS * math.radians(blur) * along + least


def write(path, **settings):
    text = effect(**settings)
    with open(path, "w", encoding="ascii", newline="\r\n") as f:
        f.write(text)
    return path


def _sync(src, dst):
    """the files of the folder src copied into dst where they are missing or differ in size or time (shutil.copy2 keeps
    the time): a model or texture rebuilt since the last copy is taken again.  Files only dst has are left (the effects)"""
    for root, _, names in os.walk(src):
        here = os.path.join(dst, os.path.relpath(root, src))
        os.makedirs(here, exist_ok=True)
        for name in names:
            a, b = os.path.join(root, name), os.path.join(here, name)
            sa = os.stat(a)
            sb = os.stat(b) if os.path.isfile(b) else None
            if sb is None or sb.st_size != sa.st_size or sb.st_mtime_ns != sa.st_mtime_ns:
                shutil.copy2(a, b)


def prepare(model, outdir, variant=None, **settings):
    """the model's folder copied into OUTDIR (and again each file that changed since: review of softshadow-mme, a copy
    kept once would draw a model rebuilt since as it was) and the effect beside the copy of MODEL: <model name>.fx, or with
    `variant` a copy of the model named <model name>[<variant>.fx].pmx beside <variant>.fx (MME takes the effect named in
    brackets in the model's file name: several effects for one model side by side).  The paths of the model to load and
    of the effect"""
    model = os.path.abspath(model)
    src = os.path.dirname(model)
    dst = os.path.join(os.path.abspath(outdir), os.path.basename(src))
    if os.path.normcase(dst) == os.path.normcase(src) or os.path.normcase(dst).startswith(os.path.normcase(src) + os.sep):
        raise ValueError("OUTDIR must not hold the model's own folder nor lie in it: the original is not written")
    if not os.path.isfile(model):
        raise ValueError("no model at %s" % model)
    _sync(src, dst)
    stem, ext = os.path.splitext(os.path.basename(model))
    copy = os.path.join(dst, stem + ext)
    if variant:
        if not variant.replace("_", "").replace("-", "").isalnum() or not variant.isascii():
            raise ValueError("a variant is a name of ASCII letters, digits, _ and -, not %r" % (variant,))
        named = os.path.join(dst, "%s[%s.fx]%s" % (stem, variant, ext))
        shutil.copy2(copy, named)
        fx = os.path.join(dst, variant + ".fx")
        copy = named
    else:
        fx = os.path.join(dst, stem + ".fx")
    write(fx, **settings)
    return {"model": copy.replace("\\", "/"), "effect": fx.replace("\\", "/")}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check(exe):
    """MME beside MMD.exe: {"installed": bool, "files": {name: "same" | "different" | "missing"}}"""
    folder = os.path.dirname(os.path.abspath(exe))
    files = {}
    for name, digest in MME_FILES.items():
        p = os.path.join(folder, name)
        files[name] = "missing" if not os.path.isfile(p) else ("same" if sha256(p) == digest else "different")
    return {"installed": all(v == "same" for v in files.values()), "files": files}


MARK = "// soft_self_shadow.fx:"         # the first line of an effect this tool wrote


def effect_of(model):
    """the effect MME applies to MODEL when MMD loads it (MMEffect.txt): the one named in brackets in its file name
    (name[effect.fx].pmx) or <name>.fx beside it; None without one"""
    folder, base = os.path.split(os.path.abspath(model))
    stem = os.path.splitext(base)[0]
    if stem.endswith("]") and "[" in stem:
        named = os.path.join(folder, stem[stem.rindex("[") + 1:-1])
        return named if os.path.isfile(named) else None
    plain = os.path.join(folder, stem + ".fx")
    return plain if os.path.isfile(plain) else None


def verify(exe, model, want):
    """does MMD at EXE render MODEL the way `want` says?  "soft": MME is installed beside EXE and MODEL has an effect this
    tool wrote; "mmd": MMD's own self shadow (no MME beside EXE, or no effect on MODEL).  ValueError when not"""
    mme = check(exe)
    fx = effect_of(model)
    if want == "soft":
        if not mme["installed"]:
            raise ValueError("self_shadow soft needs MME 0.37 beside %s: %s" % (exe, json.dumps(mme["files"])))
        if fx is None:
            raise ValueError("self_shadow soft needs an effect for %s: write it with tools/mme_shadow.py prepare" % model)
        with open(fx, encoding="ascii", errors="replace") as f:
            head = [f.readline() for _ in range(4)]
        if not head[0].startswith(MARK):
            raise ValueError("the effect %s was not written by tools/mme_shadow.py" % fx)
        settings = [line.split("Settings:")[-1].strip() for line in head if "Settings:" in line]
        try:
            values = json.loads(settings[0]) if settings else None
        except ValueError:
            values = None
        if not isinstance(values, dict):
            raise ValueError("the effect %s does not say its settings (write it again with tools/mme_shadow.py)" % fx)
        # review of softshadow-mme: the effects for measuring draw no soft shadow (--debug: the shadow alone or the body
        # lit; --sharp: MMD's own test)
        if values.get("debug") or values.get("sharp"):
            raise ValueError("the effect %s is one for measuring (debug %r, sharp %r), not the soft shadow"
                             % (fx, values.get("debug"), values.get("sharp")))
        return {"self_shadow": "soft", "effect": fx.replace("\\", "/"), "settings": settings[0]}
    if want == "mmd":
        # MME of another build than the one this tool knows applies the effect all the same (review of softshadow-mme)
        if fx is not None and (mme["installed"] or mme["files"]["MMEffect.dll"] != "missing"):
            raise ValueError("self_shadow mmd, but MME beside %s would apply %s to the model: the picture would not be "
                             "MMD's own (use the model without the effect, or self_shadow soft)" % (exe, fx))
        return {"self_shadow": "mmd", "effect": None}
    raise ValueError("self_shadow is mmd (MMD's own) or soft (tools/mme_shadow.py through MME), not %r" % (want,))


def _options(s):
    s.add_argument("--blur", type=float, default=DEFAULTS["blur"], help="the light's spread, degrees (default 5)")
    s.add_argument("--min-blur", type=float, default=DEFAULTS["min_blur"],
                   help="the least blur, a standard deviation in MMD units (default 0.05 = 4 mm: the map's stair steps)")
    s.add_argument("--taps", type=int, default=DEFAULTS["taps"])
    s.add_argument("--search-taps", type=int, default=DEFAULTS["search_taps"])
    s.add_argument("--no-contact", action="store_true", help="the same blur everywhere (--min-blur)")
    shade = s.add_mutually_exclusive_group()
    shade.add_argument("--key-share", type=float, default=DEFAULTS["key_share"],
                       help="the key light's share: the shade keeps the rest of the light (default 0.35: it keeps 0.65, "
                            "option D of 2026-10-17; 0.6 keeps 0.40 as the floor of tools/mv_world.py does, option A)")
    shade.add_argument("--toon", action="store_true", help="shade with MMD's toon colours as they are")
    s.add_argument("--debug", nargs="?", const="shadow", default=False, choices=("shadow", "lit", "toon"),
                   help="draw the shadow alone (shadow, for tools/shadow_measure.py), the body lit everywhere (lit) or "
                        "the toon's share of the light where a shade shows (toon, for tools/selfshadow_check.py against)")
    s.add_argument("--sharp", action="store_true", help="MMD's own shadow test (one point) and toon colours")


def _settings(a):
    return {"blur": a.blur, "min_blur": a.min_blur, "n_taps": a.taps, "search_taps": a.search_taps,
            "contact": not a.no_contact, "debug": a.debug, "sharp": a.sharp,
            "key_share": None if a.toon else a.key_share}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("write", help="write the effect file")
    s.add_argument("out")
    _options(s)
    s = sub.add_parser("prepare", help="copy the model's folder and write the effect beside the copy")
    s.add_argument("model")
    s.add_argument("outdir")
    s.add_argument("--variant", help="write <variant>.fx and a copy of the model named <model>[<variant>.fx].pmx")
    _options(s)
    s = sub.add_parser("check", help="is MME installed beside this MMD?")
    s.add_argument("exe")
    s = sub.add_parser("verify", help="will this MMD draw this model's self shadow as WANT says (soft / mmd)?")
    s.add_argument("exe")
    s.add_argument("model")
    s.add_argument("want", choices=("soft", "mmd"))
    a = p.parse_args(argv)
    try:
        if a.command == "write":
            out = {"ok": True, "effect": write(a.out, **_settings(a))}
        elif a.command == "prepare":
            out = dict({"ok": True}, **prepare(a.model, a.outdir, a.variant, **_settings(a)))
        elif a.command == "verify":
            out = dict({"ok": True}, **verify(a.exe, a.model, a.want))
        else:
            out = dict({"ok": True}, **check(a.exe))
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=True))
        return 2
    print(json.dumps(out, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
