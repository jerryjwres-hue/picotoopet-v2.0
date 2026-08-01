// 明确 WPF 对话框类型，避免启用内置 Windows Forms 托盘后产生同名类型歧义。
global using MessageBox = System.Windows.MessageBox;
