from pathlib import Path

p = Path('geto.py')
text = p.read_text(encoding='utf-8')

old_interact = '''def on_interact(event):
    """Обработка ПКМ по земле яйцом Гето."""
'''
new_interact = '''def on_interact(event):
    """Обработка ПКМ по земле яйцом Гето."""
    # PySpigot допускает только один listener одного Event-класса на скрипт.
    # Узумаки подключается как хук к уже зарегистрированному PlayerInteractEvent.
    try:
        if "_uz_on_interact" in globals():
            _uz_on_interact(event)
            if event.isCancelled():
                return
    except Exception as ex:
        Bukkit.getLogger().warning("[geto][uzumaki] interact hook: " + str(ex))
'''
if old_interact not in text:
    raise SystemExit('on_interact anchor not found')
text = text.replace(old_interact, new_interact, 1)

old_damage = '''def on_damage_by(event):
    dmg = event.getDamager()
'''
new_damage = '''def on_damage_by(event):
    # Узумаки использует тот же EntityDamageByEntityEvent через общий хук,
    # чтобы не регистрировать второй listener в PySpigot.
    try:
        if "_uz_on_damage_by" in globals():
            _uz_on_damage_by(event)
            if event.isCancelled():
                return
    except Exception as ex:
        Bukkit.getLogger().warning("[geto][uzumaki] damage hook: " + str(ex))
    dmg = event.getDamager()
'''
if old_damage not in text:
    raise SystemExit('on_damage_by anchor not found')
text = text.replace(old_damage, new_damage, 1)

text = text.replace('listener_mgr.registerListener(_uz_on_interact, PlayerInteractEvent)\n', '', 1)
text = text.replace('listener_mgr.registerListener(_uz_on_damage_by, EntityDamageByEntityEvent)\n', '', 1)

p.write_text(text, encoding='utf-8')
