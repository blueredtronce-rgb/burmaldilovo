# -*- coding: utf-8 -*-
"""
CONTACT barrier extension for SmartY-Anomalies.
Loaded after anomaly_research.inc so it becomes the final CONTACT transmission
implementation.

Rules:
- Physical blocks between an infectious source and a healthy target reduce the
  CONTACT roll by 70% (x0.30).
- TINTED_GLASS is a special research material: if it is between the players,
  the resulting CONTACT chance is capped at 1% per normal infection check.
- Armor and block protection DO NOT stack. Whichever gives the greater
  protection (the lower final infection chance) is used.
- Mk.I remains 95% CONTACT protection; Mk.II remains 100% while complete.
- Mk.II only takes exposure wear when there is no physical barrier between the
  players; a wall/glass barrier means the suit itself is not being exposed.

PySpigot / Jython 2.7 / Paper-Leaf 1.21.x.
"""

CONTACT_BLOCK_FACTOR = 0.30
CONTACT_TINTED_GLASS_MAX_CHANCE = 0.01
CONTACT_BARRIER_SAMPLE_STEP = 0.20


def _contact_barrier_material_at(world, x, y, z):
    try:
        block = world.getBlockAt(
            int(math.floor(float(x))),
            int(math.floor(float(y))),
            int(math.floor(float(z)))
        )
        material = block.getType()
        if material is None:
            return None
        try:
            if material.isAir():
                return None
        except Exception:
            if to_unicode(material.name()).endswith(u"AIR"):
                return None

        # Fluids, grass and other passable blocks are not real separators.
        try:
            if block.isPassable():
                return None
        except Exception:
            pass
        return material
    except Exception:
        return None


def _contact_barrier_between(source, target):
    """Return 'TINTED', 'BLOCK', or None for physical separation."""
    try:
        if source.getWorld() != target.getWorld():
            return None
        world = source.getWorld()
        a = source.getLocation()
        b = target.getLocation()

        dx = float(b.getX() - a.getX())
        dz = float(b.getZ() - a.getZ())
        if math.sqrt(dx * dx + dz * dz) <= 0.15:
            return None

        found_block = False
        found_tinted = False

        # Three body-height rays so a real wall counts even if eye-level alone
        # would pass over/under a partial barrier.
        for height in (0.45, 1.05, 1.62):
            sx = float(a.getX())
            sy = float(a.getY()) + float(height)
            sz = float(a.getZ())
            ex = float(b.getX())
            ey = float(b.getY()) + float(height)
            ez = float(b.getZ())

            vx = ex - sx
            vy = ey - sy
            vz = ez - sz
            distance = math.sqrt(vx * vx + vy * vy + vz * vz)
            if distance <= 0.40:
                continue

            steps = max(1, int(distance / CONTACT_BARRIER_SAMPLE_STEP))
            seen = set()
            for index in range(1, steps):
                ratio = float(index) / float(steps)
                x = sx + vx * ratio
                y = sy + vy * ratio
                z = sz + vz * ratio
                key = (
                    int(math.floor(x)),
                    int(math.floor(y)),
                    int(math.floor(z))
                )
                if key in seen:
                    continue
                seen.add(key)

                material = _contact_barrier_material_at(world, x, y, z)
                if material is None:
                    continue

                if to_unicode(material.name()) == u"TINTED_GLASS":
                    found_tinted = True
                else:
                    found_block = True

        if found_tinted:
            return u"TINTED"
        if found_block:
            return u"BLOCK"
    except Exception:
        pass
    return None


def _contact_chance_after_protection(controller, target, base_chance, barrier_kind):
    """Use the strongest single protection source; protections do not stack."""
    base_chance = max(0.0, float(base_chance))
    state = _research_suit_state(controller, target)

    armor_chance = base_chance
    if state.get("full2"):
        armor_chance = 0.0
    elif state.get("full1"):
        armor_chance = base_chance * RESEARCH_SUIT1_CONTACT_FACTOR

    block_chance = base_chance
    if barrier_kind == u"TINTED":
        block_chance = min(base_chance, CONTACT_TINTED_GLASS_MAX_CHANCE)
    elif barrier_kind == u"BLOCK":
        block_chance = base_chance * CONTACT_BLOCK_FACTOR

    return min(armor_chance, block_chance)


try:
    def _barrier_contact_spread(self, players, now):
        if now < self.contact_next:
            return
        self.contact_next = now + INF_CONTACT_INTERVAL

        infectious = []
        healthy = []
        for player in players:
            record = self.record(player)
            if record is None:
                healthy.append(player)
            elif safe_int(record.get("stage"), 1, 1, 3) >= 2:
                infectious.append(player)

        for target in healthy:
            nearest = None
            nearest_distance = INF_CONTACT_RADIUS + 1.0
            for source in infectious:
                try:
                    if source.getWorld() != target.getWorld():
                        continue
                    distance = source.getLocation().distance(target.getLocation())
                    if distance <= INF_CONTACT_RADIUS and distance < nearest_distance:
                        nearest = source
                        nearest_distance = distance
                except Exception:
                    continue

            if nearest is None:
                continue

            base_chance = self._contact_chance(nearest_distance)
            if base_chance <= 0.0:
                continue

            barrier_kind = _contact_barrier_between(nearest, target)
            state = _research_suit_state(self, target)

            # Mk.II gives 100% CONTACT protection while intact. Exposure wear is
            # applied only with a clear physical path to the infectious player.
            if state.get("full2"):
                if barrier_kind is None:
                    _research_damage_mk2(self, target, nearest_distance)
                continue

            chance = _contact_chance_after_protection(
                self, target, base_chance, barrier_kind
            )

            if chance > 0.0 and random.random() < chance:
                self.infect(
                    target,
                    "CONTACT",
                    anomaly=None,
                    source_player=nearest,
                    stage=1,
                    contact_distance=nearest_distance,
                    contact_chance=chance
                )

    AnomalyInfectionController._contact_spread = _barrier_contact_spread
    log_action(
        u"CONTACT barriers installed: physical blocks x0.30, TINTED_GLASS cap=1%, best-of armor/barrier protection."
    )
except Exception as _contact_barrier_install_error:
    try:
        log_error(u"Cannot install CONTACT barrier extension", _contact_barrier_install_error)
    except Exception:
        pass
