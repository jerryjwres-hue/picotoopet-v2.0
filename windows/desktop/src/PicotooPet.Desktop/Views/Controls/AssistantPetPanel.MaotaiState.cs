namespace PicotooPet.Desktop.Views.Controls;

public partial class AssistantPetPanel
{
    // Mood readback     : presentation-only diagnostic state; never participates in task/Core decisions.
    internal string MaotaiVisualMood => _maotaiMood.ToString();
}
