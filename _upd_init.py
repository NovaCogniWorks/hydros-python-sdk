import pathlib

p = pathlib.Path(r'E:\Workspace\WJH\hydros-python-sdk\hydros_agent_sdk\agents\__init__.py')
content = p.read_text('utf-8')
lines = content.splitlines()
new_lines = []

inserted = False
for line in lines:
    new_lines.append(line)
    if not inserted and line.startswith('from .outflow_plan_agent'):
        new_lines.append('from .controller_agent import ControllerAgent')
        inserted = True

new_content = '\n'.join(new_lines)

# Update __all__
old = 'OutflowPlanAgent','
new = 'OutflowPlanAgent',\n    'ControllerAgent','
new_content = new_content.replace(old, new)

p.write_text(new_content, 'utf-8')
print('Updated __init__.py')
print(new_content)
