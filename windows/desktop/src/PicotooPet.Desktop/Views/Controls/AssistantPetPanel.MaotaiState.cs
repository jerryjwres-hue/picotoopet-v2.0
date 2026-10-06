namespace PicotooPet.Desktop.Views.Controls;

public partial class AssistantPetPanel
{
    // Motion readback   : presentation-only diagnostic state; never participates in task/Core decisions.
    internal string MaotaiVisualMood =>
        _maotaiMotionEngine?.ActiveState.ToString() ?? "Unavailable";
}
