// Camera maths for scene_probe shots: describe what has to be in frame, not where to stand.
// Minecraft: yaw 0 looks at +Z, 90 at -X, 180 at -Z, 270 at +X; pitch is positive looking down.
// The eye sits 1.62 above the feet -- the number hand-written cameras kept getting wrong, which
// turned half a test run into pictures of the sky.

export const EYE_HEIGHT = 1.62;
export const FOV_Y = 70; // vanilla default, no zoom
export const DEFAULT_ZOOM = 3.0; // frame fill: 1 = the subject touches the edge

const rad = (d) => (d * Math.PI) / 180;
const deg = (r) => (r * 180) / Math.PI;
const round = (v) => Math.round(v * 100) / 100;

export function aim(eye, target) {
  const dx = target[0] - eye[0];
  const dy = target[1] - eye[1];
  const dz = target[2] - eye[2];
  let yaw = deg(Math.atan2(-dx, dz));
  if (yaw < 0) yaw += 360;
  return {
    yaw: round(yaw),
    pitch: round(-deg(Math.atan2(dy, Math.hypot(dx, dz)))),
    distance: round(Math.hypot(dx, dy, dz)),
  };
}

// A block coordinate is a point; what the camera must frame is its unit cube.
export function subjectBox(blocks, pad = 0) {
  const points = blocks.map((b) => (Array.isArray(b) ? b : [b.x, b.y, b.z]));
  const low = [0, 1, 2].map((i) => Math.min(...points.map((p) => p[i])) - pad);
  const high = [0, 1, 2].map((i) => Math.max(...points.map((p) => p[i])) + 1 + pad);
  const center = [0, 1, 2].map((i) => (low[i] + high[i]) / 2);
  const size = [0, 1, 2].map((i) => high[i] - low[i]);
  return { low, high, center, size, radius: Math.hypot(...size) / 2 };
}

function fitDistance(box, aspect, zoom) {
  const tanY = Math.tan(rad(FOV_Y / 2));
  const vertical = box.size[1] / 2 / tanY;
  const horizontal = Math.max(box.size[0], box.size[2]) / 2 / (tanY * aspect);
  return Math.max(vertical, horizontal) * zoom;
}

// azimuth: compass bearing of the camera around the subject, 0 = north of it (lower z), 90 = east.
// elevation: degrees above the subject's centre; ignored when feet is given, which pins the camera
// on the ground at that y (the usual case: the player cannot fly).
export function shotFor({ blocks, azimuth = 0, elevation = 15, distance = null, zoom = DEFAULT_ZOOM,
                          feet = null, width = 1920, height = 1080, pad = 0 }) {
  const box = subjectBox(blocks, pad);
  const aspect = width / height;
  const range = distance === null ? fitDistance(box, aspect, zoom) : distance;
  const a = rad(azimuth);
  const e = rad(elevation);
  const horizontal = range * Math.cos(e);
  const eye = [
    box.center[0] + Math.sin(a) * horizontal,
    feet === null ? box.center[1] + range * Math.sin(e) : feet + EYE_HEIGHT,
    box.center[2] - Math.cos(a) * horizontal,
  ];
  const look = aim(eye, box.center);
  const camera = {
    x: round(eye[0]),
    y: round(feet === null ? eye[1] : feet),
    z: round(eye[2]),
    yaw: look.yaw,
    pitch: look.pitch,
  };
  return { camera, eye, distance: look.distance, subject: box, zoom };
}

// The camera belongs on the side the subject is exposed from: with a wall lamp, the support block
// sits between a careless camera and the lamp, and the shot becomes a picture of the wall. Given the
// blocks that occlude it, take the bearing on the far side of the subject.
export function azimuthAway(center, blockers) {
  if (!blockers || !blockers.length) return null;
  const other = subjectBox(blockers).center;
  const dx = center[0] - other[0];
  const dz = center[2] - other[2];
  if (Math.hypot(dx, dz) < 1e-6) return null;
  let bearing = deg(Math.atan2(dx, -dz));
  if (bearing < 0) bearing += 360;
  return round(bearing);
}

// Where the subject lands in the screenshot, so no crop rectangle is ever hand-guessed.
export function projectBox(box, eye, yawDeg, pitchDeg, width, height) {
  const yaw = rad(yawDeg);
  const pitch = rad(pitchDeg);
  const forward = [-Math.sin(yaw) * Math.cos(pitch), -Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch)];
  const right = [Math.cos(yaw), 0, Math.sin(yaw)];
  const up = [
    forward[1] * right[2] - forward[2] * right[1],
    forward[2] * right[0] - forward[0] * right[2],
    forward[0] * right[1] - forward[1] * right[0],
  ];
  const tanY = Math.tan(rad(FOV_Y / 2));
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  let behind = false;
  for (const x of [box.low[0], box.high[0]]) {
    for (const y of [box.low[1], box.high[1]]) {
      for (const z of [box.low[2], box.high[2]]) {
        const v = [x - eye[0], y - eye[1], z - eye[2]];
        const depth = v[0] * forward[0] + v[1] * forward[1] + v[2] * forward[2];
        if (depth <= 0.05) { behind = true; continue; }
        const sx = (v[0] * right[0] + v[1] * right[1] + v[2] * right[2]) / depth / (tanY * (width / height));
        const sy = (v[0] * up[0] + v[1] * up[1] + v[2] * up[2]) / depth / tanY;
        const px = width * 0.5 + sx * width * 0.5;
        const py = height * 0.5 - sy * height * 0.5;
        minX = Math.min(minX, px); maxX = Math.max(maxX, px);
        minY = Math.min(minY, py); maxY = Math.max(maxY, py);
      }
    }
  }
  if (!Number.isFinite(minX)) return null;
  const w = Math.max(maxX - minX, 6);
  const h = Math.max(maxY - minY, 6);
  const grow = 0.18;
  return {
    behind,
    bbox: [
      Math.max(0, Math.round(minX - w * grow)),
      Math.max(0, Math.round(minY - h * grow)),
      Math.min(width, Math.round(maxX + w * grow)),
      Math.min(height, Math.round(maxY + h * grow)),
    ],
    size: [Math.round(maxX - minX), Math.round(maxY - minY)],
  };
}
