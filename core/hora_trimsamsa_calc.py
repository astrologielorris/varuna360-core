from core.aditya_data import ADITYA_NAMES


def resolve_planet_position(sign_index, decimal_degrees):
    from AI_tools.AI_main_function.retinue import get_hora, get_trimsamsa_being

    aditya_sign_name = ADITYA_NAMES[sign_index % 12]
    degree_in_sign = decimal_degrees % 30

    hora_result = get_hora(aditya_sign_name, degree_in_sign)
    trimsamsa_result = get_trimsamsa_being(aditya_sign_name, degree_in_sign)

    hora_key = hora_result["side"].lower()
    trimsamsa_key = trimsamsa_result["being_type"].lower()

    return aditya_sign_name, hora_key, trimsamsa_key
