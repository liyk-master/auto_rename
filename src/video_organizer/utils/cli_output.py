import sys
import time
from datetime import datetime


# 颜色代码
class Colors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


# 支持不同平台的颜色显示
try:
    import colorama

    colorama.init()
    COLOR_SUPPORTED = True
except ImportError:
    # 在不支持颜色的平台上，使用空字符串代替颜色代码
    if sys.platform == "win32":
        COLOR_SUPPORTED = False
    else:
        # 尝试检测终端是否支持颜色
        COLOR_SUPPORTED = sys.stdout.isatty()


# 如果不支持颜色，将所有颜色代码替换为空字符串
if not COLOR_SUPPORTED:
    Colors.HEADER = ""
    Colors.OKBLUE = ""
    Colors.OKGREEN = ""
    Colors.WARNING = ""
    Colors.FAIL = ""
    Colors.ENDC = ""
    Colors.BOLD = ""
    Colors.UNDERLINE = ""


class CLIOutput:
    """
    命令行输出美化工具类
    """

    def __init__(self, quiet=False, color=True):
        """
        初始化命令行输出工具

        Args:
            quiet: 是否静默模式（不输出信息）
            color: 是否使用颜色输出
        """
        self.quiet = quiet
        self.color_enabled = color and COLOR_SUPPORTED

    def print_header(self, message):
        """
        打印标题信息

        Args:
            message: 要打印的消息
        """
        if self.quiet:
            return

        if self.color_enabled:
            print(f"{Colors.HEADER}{Colors.BOLD}{message}{Colors.ENDC}")
        else:
            print(f"{message}")

    def print_info(self, message):
        """
        打印信息

        Args:
            message: 要打印的消息
        """
        if self.quiet:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self.color_enabled:
            print(f"{Colors.OKBLUE}[{timestamp}] {message}{Colors.ENDC}")
        else:
            print(f"[{timestamp}] {message}")

    def print_success(self, message):
        """
        打印成功信息

        Args:
            message: 要打印的消息
        """
        if self.quiet:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self.color_enabled:
            print(f"{Colors.OKGREEN}[{timestamp}] ✓ {message}{Colors.ENDC}")
        else:
            print(f"[{timestamp}] ✓ {message}")

    def print_warning(self, message):
        """
        打印警告信息

        Args:
            message: 要打印的消息
        """
        if self.quiet:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self.color_enabled:
            print(f"{Colors.WARNING}[{timestamp}] ⚠ {message}{Colors.ENDC}")
        else:
            print(f"[{timestamp}] ⚠ {message}")

    def print_error(self, message, error=None):
        """
        打印错误信息

        Args:
            message: 要打印的消息
            error: 错误对象
        """
        if self.quiet:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self.color_enabled:
            print(f"{Colors.FAIL}[{timestamp}] ✗ {message}{Colors.ENDC}")
        else:
            print(f"[{timestamp}] ✗ {message}")

        # 如果提供了错误对象，打印错误详情
        if error is not None:
            if self.color_enabled:
                print(f"{Colors.FAIL}  错误详情: {str(error)}{Colors.ENDC}")
            else:
                print(f"  错误详情: {str(error)}")

    def print_progress(self, progress, total, message="处理中..."):
        """
        打印进度条

        Args:
            progress: 当前进度
            total: 总进度
            message: 进度条前缀消息
        """
        if self.quiet:
            return

        # 计算百分比
        percent = (progress / total) * 100

        # 进度条长度
        bar_length = 30
        filled_length = int(bar_length * progress / total)

        # 构建进度条
        if self.color_enabled:
            bar = f"{Colors.OKGREEN}{'█' * filled_length}{Colors.WARNING}{'░' * (bar_length - filled_length)}{Colors.ENDC}"
            print(f"\r{message} |{bar}| {percent:.1f}%", end="")
        else:
            bar = f"{'█' * filled_length}{'░' * (bar_length - filled_length)}"
            print(f"\r{message} |{bar}| {percent:.1f}%", end="")

        # 完成时换行
        if progress >= total:
            print()

    def print_table(self, headers, rows, max_width=80):
        """
        打印表格

        Args:
            headers: 表头列表
            rows: 数据行列表
            max_width: 最大宽度
        """
        if self.quiet:
            return

        if not rows:
            return

        # 计算每列的最大宽度
        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                if i < len(widths):
                    widths[i] = max(widths[i], len(str(cell)))

        # 计算总宽度
        total_width = sum(widths) + len(widths) * 3 + 1
        if total_width > max_width:
            # 如果总宽度超过最大宽度，调整每列宽度
            scale = (max_width - len(widths) * 3 - 1) / total_width
            widths = [int(w * scale) for w in widths]

        # 打印表头
        self._print_table_line(widths)
        self._print_table_row(headers, widths, bold=True)
        self._print_table_line(widths, double=True)

        # 打印数据行
        for row in rows:
            self._print_table_row(row, widths)

        # 打印表格底部
        self._print_table_line(widths)

    def _print_table_line(self, widths, double=False):
        """
        打印表格分隔线

        Args:
            widths: 列宽度列表
            double: 是否使用双分隔线
        """
        if double:
            line = "├"
            for width in widths[:-1]:
                line += "┼"
            line += "┤"
        else:
            line = "┌"
            for width in widths[:-1]:
                line += "┬"
            line += "┐"

        print(line)

    def _print_table_row(self, cells, widths, bold=False):
        """
        打印表格行

        Args:
            cells: 单元格数据列表
            widths: 列宽度列表
            bold: 是否粗体显示
        """
        row = "│"
        for i, (cell, width) in enumerate(zip(cells, widths)):
            cell_str = str(cell)[:width]  # 截断过长的内容
            padding = width - len(cell_str)

            if self.color_enabled and bold:
                cell_str = f"{Colors.BOLD}{cell_str}{Colors.ENDC}"

            row += f" {cell_str}{' ' * padding} │"

        print(row)

    def print_separator(self):
        """
        打印分隔线
        """
        if self.quiet:
            return

        if self.color_enabled:
            print(f"{Colors.WARNING}{'-' * 72}{Colors.ENDC}")
        else:
            print("-" * 72)

    def ask_confirmation(self, message="确定要继续吗？"):
        """
        询问用户确认

        Args:
            message: 询问消息

        Returns:
            用户是否确认 (True/False)
        """
        if self.quiet:
            return True

        while True:
            if self.color_enabled:
                response = input(f"{Colors.OKBLUE}{message} (y/n): {Colors.ENDC}")
            else:
                response = input(f"{message} (y/n): ")

            response = response.lower().strip()
            if response in ("y", "yes"):
                return True
            elif response in ("n", "no"):
                return False

    def clear_screen(self):
        """
        清屏
        """
        if not self.quiet:
            import os

            os.system("cls" if os.name == "nt" else "clear")


def get_cli_output(quiet=False, color=True):
    """
    获取命令行输出工具实例

    Args:
        quiet: 是否静默模式
        color: 是否使用颜色

    Returns:
        CLIOutput实例
    """
    return CLIOutput(quiet=quiet, color=color)
