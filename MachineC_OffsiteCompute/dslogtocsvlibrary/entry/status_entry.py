from __future__ import annotations


class StatusEntry:
    def __init__(
        self,
        brownout,
        watchdog,
        ds_teleop,
        ds_disabled,
        robot_teleop,
        robot_autonomous,
        robot_disabled,
    ) -> None:
        self.brownout = brownout
        self.watchdog = watchdog
        self.ds_teleop = ds_teleop
        self.ds_disabled = ds_disabled
        self.robot_teleop = robot_teleop
        self.robot_autonomous = robot_autonomous
        self.robot_disabled = robot_disabled

    @classmethod
    def from_int(cls, status: int) -> StatusEntry:
        return cls(
            brownout=(status >> 7) & 1,
            watchdog=(status >> 6) & 1,
            ds_teleop=(status >> 5) & 1,
            ds_disabled=(status >> 3) & 1,
            robot_teleop=(status >> 2) & 1,
            robot_autonomous=(status >> 1) & 1,
            robot_disabled=status & 1,
        )

    def __str__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"brownout={self.brownout}, "
            f"watchdog={self.watchdog}, "
            f"ds_teleop={self.ds_teleop}, "
            f"ds_disabled={self.ds_disabled}, "
            f"robot_teleop={self.robot_teleop}, "
            f"robot_autonomous={self.robot_autonomous}, "
            f"robot_disabled={self.robot_disabled})"
        )
