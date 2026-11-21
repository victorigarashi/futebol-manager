import * as THREE from "three";

/**
 * Analytic two-bone IK (hip-knee-ankle or shoulder-elbow-wrist), after D. Holden's
 * formulation: keeps the bend plane the animation already has (no pole vector needed),
 * changes the two joint angles so the end reaches `target`, and optionally restores the
 * end bone's world rotation (feet stay flat as animated).
 */
const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
const ab = new THREE.Vector3(), ac = new THREE.Vector3(), at = new THREE.Vector3(), ba = new THREE.Vector3(), bc = new THREE.Vector3();
const axis0 = new THREE.Vector3(), axis1 = new THREE.Vector3(), tmp = new THREE.Vector3();
const qa = new THREE.Quaternion(), qb = new THREE.Quaternion(), qInv = new THREE.Quaternion(), qr = new THREE.Quaternion(), qEnd = new THREE.Quaternion(), qParent = new THREE.Quaternion();
const clamp = (x: number) => Math.max(-1, Math.min(1, x));

export function twoBoneIK(root: THREE.Bone, mid: THREE.Bone, end: THREE.Bone, target: THREE.Vector3, weight = 1, keepEndRotation = true): void {
  if (weight <= 0) return;
  root.updateWorldMatrix(true, true);
  root.getWorldPosition(a); mid.getWorldPosition(b); end.getWorldPosition(c);
  if (keepEndRotation) end.getWorldQuaternion(qEnd);
  const lab = ab.subVectors(b, a).length(), lcb = bc.subVectors(c, b).length();
  const tgt = tmp.copy(c).lerp(target, weight);
  const lat = Math.max(0.01, Math.min(lab + lcb - 1e-3, at.subVectors(tgt, a).length()));
  ac.subVectors(c, a);
  const acLen = ac.length();
  const ac_ab_0 = Math.acos(clamp(ac.clone().normalize().dot(ab.clone().normalize())));
  const ba_bc_0 = Math.acos(clamp(ba.subVectors(a, b).normalize().dot(bc.clone().normalize())));
  const ac_at_0 = Math.acos(clamp(ac.clone().normalize().dot(at.clone().normalize())));
  const ac_ab_1 = Math.acos(clamp((lcb * lcb - lab * lab - lat * lat) / (-2 * lab * lat)));
  const ba_bc_1 = Math.acos(clamp((lat * lat - lab * lab - lcb * lcb) / (-2 * lab * lcb)));
  axis0.crossVectors(ac, ab);
  if (axis0.lengthSq() < 1e-10) axis0.set(1, 0, 0); else axis0.normalize();
  axis1.crossVectors(ac, at);
  const hasAxis1 = axis1.lengthSq() > 1e-10 && acLen > 1e-6;
  if (hasAxis1) axis1.normalize();
  root.getWorldQuaternion(qa);
  mid.getWorldQuaternion(qb);
  // rotations expressed in each bone's local frame
  qInv.copy(qa).invert();
  const r0 = qr.setFromAxisAngle(tmp.copy(axis0).applyQuaternion(qInv), ac_ab_1 - ac_ab_0);
  root.quaternion.multiply(r0);
  qInv.copy(qb).invert();
  mid.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(tmp.copy(axis0).applyQuaternion(qInv), ba_bc_1 - ba_bc_0));
  if (hasAxis1) {
    qInv.copy(qa).invert();
    root.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(tmp.copy(axis1).applyQuaternion(qInv), ac_at_0));
  }
  if (keepEndRotation) {
    root.updateWorldMatrix(true, true);
    (end.parent as THREE.Object3D).getWorldQuaternion(qParent);
    end.quaternion.copy(qParent.invert().multiply(qEnd));
  }
  root.updateWorldMatrix(true, true);
}
