"""Which chart an Avastha screen reads (td-tknsx).

One home for the rule so the matrix, the dignity diagonal and the lajjitaadi
states always come from the same chart, the one the screen displays: sidereal
mode reads a sidereal rebuild (identical to ``chart`` when it was already
built sidereal), every other mode reads ``chart`` itself.
"""


def avastha_frame_chart(chart, mode):
    if mode == "sidereal":
        from core.chart_factory import rebuild_chart
        return rebuild_chart(chart, mode="sidereal")
    return chart
