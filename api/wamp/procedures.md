
# Procedures

## Player

Prefixed with "player."

enqueue()
dequeue()

move()
skip_next()
skip_prev()

pause()
seek()
volume()

## RBAC

Prefixed with "rbac."

get_role()
    Get a role by its name or id.
    
get_roles(target)
    Get the roles for a target.

assign_role(role, target)
    Add a role to a target.
unassign_role(role, target)
    Remove a role from a target.

create_role()
    Create a new role.
delete_role()
    Delete a role.